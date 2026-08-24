// Package rotationexecute is the ordinary-rotation orchestration entry
// point ADR-044 §17 items 1 and 3 record as missing (a production path that
// can initiate a real, governed authority rotation beyond the one-time
// genesis transition bootstrap.ExecuteGenesis already implements). It
// composes rotationprepare (pre-commit read/CAS + mutation construction)
// and rotationcommit.CompleteRotationCommit (the real Commit + V2 signing
// boundary) with the same fail-closed epoch state machine
// (internal/authority/epoch) and the same immutable GCS witness boundary
// (gcswitness) bootstrap already uses for genesis.
//
// This package is deliberately domain-separated from bootstrap: it never
// imports bootstrap, never constructs a GenesisRequest, never uses
// protocol.DomainNewEpochGenesis, and never writes to the one-time bootstrap
// path's own witness-key namespace. Genesis and ordinary rotation remain
// two structurally distinct paths sharing only the lower S1-S3 primitives
// both already relied on before this package existed.
package rotationexecute

import (
	"context"
	"errors"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationprepare"
)

// SpannerClient is every Spanner capability an ordinary rotation needs:
// rotationprepare's pre-commit read/CAS boundary plus
// rotationcommit.RawCommitClient's single Commit RPC. In production this is
// satisfied directly by the same raw generated spannerpb.SpannerClient stub
// every other production Spanner boundary in this codebase already uses
// (spannerpb.NewSpannerClient wrapping the connection spannercommit.Dial
// opens) -- this package introduces no second Spanner connection type.
type SpannerClient interface {
	rotationprepare.RotationSpannerClient
	rotationcommit.RawCommitClient
}

// Dependencies is every production capability ExecuteRotation needs.
type Dependencies struct {
	Spanner         SpannerClient
	SpannerDatabase string
	Witness         gcswitness.ImmutableWitness
	Signer          rotationcommit.Signer
}

// Outcome classifies the result of one ExecuteRotation call. Its meanings
// deliberately mirror bootstrap.Outcome's -- the same fail-closed
// vocabulary applies to every Recovery Authority state transition, genesis
// or ordinary -- but this is an independent type: ExecuteRotation never
// returns a bootstrap.Outcome, and bootstrap never returns this one.
type Outcome int

const (
	// OutcomeUnknown is the zero value -- never a real result.
	OutcomeUnknown Outcome = iota
	// OutcomeRejected means the candidate was refused by rotationprepare's
	// own pre-commit read/CAS check (Attacks B/D/E/F), or by input
	// validation, before Commit was ever attempted. Safe to correct and
	// retry with a fresh read of current state.
	OutcomeRejected
	// OutcomeCompleted means this call performed the real Commit, real
	// signing, and real witness write, and the epoch is now StateActive.
	OutcomeCompleted
	// OutcomeUnresolved means a provider mutation was attempted (Spanner
	// Commit and/or GCS witness write) and its outcome could not be
	// established as a clean, unambiguous success. Per ADR-044 §8/§9, this
	// is the NEW_EPOCH_REQUIRED case: this exact candidate (same operation
	// ID) must never be retried automatically.
	OutcomeUnresolved
)

func (o Outcome) String() string {
	switch o {
	case OutcomeRejected:
		return "REJECTED"
	case OutcomeCompleted:
		return "COMPLETED"
	case OutcomeUnresolved:
		return "UNRESOLVED"
	default:
		return "UNKNOWN"
	}
}

// Result is ExecuteRotation's full, evidence-bearing outcome.
type Result struct {
	Outcome        Outcome
	Classification rotationcommit.CommitClassification
	EpochState     epoch.State
	WitnessCreate  gcswitness.CreateOutcome
	StateDigest    protocol.Digest32
	OperationID    string
	PrepareRefusal string
	// SessionName and TransactionID identify the exact Spanner
	// session/transaction a Commit was attempted under, whenever a
	// CommitRequest was built (i.e. whenever PrepareRefusal is empty) --
	// real production evidence for audit/debugging, and (for an
	// ambiguous/unresolved outcome) the identifiers a caller needs to issue
	// its own best-effort Rollback to release provider-side resources; this
	// package never issues that Rollback itself, since doing so after an
	// ambiguous Commit must never be conflated with resolving the ambiguity.
	SessionName   string
	TransactionID []byte
}

var ErrRotationUnresolved = errors.New("rotationexecute: rotation outcome could not be established as unambiguous success; NEW_EPOCH_REQUIRED-style manual review required")

// WitnessKey is the deterministic GCS witness object key an ordinary
// rotation writes to. Its "rotation/" prefix, distinct from the one-time
// bootstrap path's own prefix, is a second, independent layer of domain
// separation beyond the state-digest domain separator alone: even an
// operator scanning the witness bucket's key namespace can immediately
// distinguish the two record families, and no candidate constructed by this
// package can ever collide with a first-epoch witness key.
func WitnessKey(candidate rotationprepare.Candidate, proposedRevision protocol.RevisionNumber) string {
	return fmt.Sprintf(
		"rotation/%s/%s/%s/%s.json",
		candidate.EnvironmentID.String(),
		candidate.ResourceIncarnation.String(),
		candidate.AuthorityEpoch.String(),
		proposedRevision.String(),
	)
}

// ExecuteRotation is the sole orchestration entry point this package
// exposes. candidate is the caller's declared intent; this function
// performs the real pre-commit read/CAS check, the real Commit, the real
// V2 signing, and the real GCS witness write -- in that order, never out
// of order, and never resolving an ambiguous outcome by reading again.
func ExecuteRotation(ctx context.Context, deps Dependencies, candidate rotationprepare.Candidate) (Result, error) {
	prepared, err := rotationprepare.PrepareOrdinaryRotation(ctx, deps.Spanner, deps.SpannerDatabase, candidate)
	if err != nil {
		return Result{Outcome: OutcomeRejected}, fmt.Errorf("rotationexecute: prepare: %w", err)
	}
	if !prepared.Ready {
		// Commit was never attempted -- ClassifyCommit(false, ...) is the
		// exact classification the emulator T13 conformance test already
		// asserts for this case (ReasonCommitNotInvoked), reused here
		// rather than reinvented.
		classification := rotationcommit.ClassifyCommit(false, nil, nil, rotationcommit.RegularSession)
		return Result{
			Outcome:        OutcomeRejected,
			Classification: classification,
			EpochState:     epoch.TransitionOnCASOutcome(classification.Outcome),
			PrepareRefusal: prepared.Reason,
		}, fmt.Errorf("rotationexecute: candidate refused before Commit: %s", prepared.Reason)
	}

	base := Result{SessionName: prepared.SessionName, TransactionID: prepared.TransactionID}

	payload, classification, commitErr := rotationcommit.CompleteRotationCommit(
		ctx, deps.Spanner, prepared.CommitRequest, prepared.Operation, prepared.TransactionID, deps.Signer,
	)
	if commitErr != nil {
		resultState := epoch.TransitionOnCASOutcome(classification.Outcome)
		base.Classification, base.EpochState = classification, resultState
		if resultState == epoch.StateActive {
			// UnambiguousNotCommitted: Spanner itself proved nothing
			// changed. Safe to retry with a fresh PrepareOrdinaryRotation
			// call (current state has not moved).
			base.Outcome = OutcomeRejected
			return base, fmt.Errorf("rotationexecute: commit not accepted: %w (classification reason %d)", commitErr, classification.Reason)
		}
		base.Outcome = OutcomeUnresolved
		return base, fmt.Errorf("%w: Spanner commit outcome %s: %v", ErrRotationUnresolved, classification.Outcome, commitErr)
	}
	base.Classification = classification

	wireBytes, err := protocol.MarshalCommittedPayloadJSON(payload)
	if err != nil {
		base.Outcome, base.EpochState = OutcomeUnresolved, epoch.StateRecoveryFrozenPendingWitness
		return base, fmt.Errorf("%w: encode committed witness payload: %v", ErrRotationUnresolved, err)
	}

	witnessKey := WitnessKey(candidate, prepared.Operation.ProposedRevision())
	createOutcome, createErr := deps.Witness.CreateExactIfAbsent(ctx, witnessKey, wireBytes)
	witnessed := createOutcome == gcswitness.CreateSuccess || createOutcome == gcswitness.AlreadyExistsIdentical
	resultState := epoch.TransitionOnWitnessOutcome(witnessed)
	result := base
	result.EpochState = resultState
	result.WitnessCreate = createOutcome
	result.StateDigest = prepared.StateDigest
	result.OperationID = prepared.Operation.OperationID().String()
	if !witnessed {
		reason := createErr
		if reason == nil {
			reason = fmt.Errorf("witness create outcome %s", createOutcome)
		}
		result.Outcome = OutcomeUnresolved
		return result, fmt.Errorf("%w: GCS witness create outcome %s: %v", ErrRotationUnresolved, createOutcome, reason)
	}
	result.Outcome = OutcomeCompleted
	return result, nil
}

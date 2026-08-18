// Package bootstrap implements the S6 governed genesis/first-epoch
// mechanism ADR-044/045 require before any environment's Recovery
// Authority can be provisioned for the first time. It is not a general
// rotation-writer harness (spannercommit's own doc comment defers that to
// a separately-scoped PREPARE/CAS layer that still does not exist) -- it
// is narrowly scoped to the one-time transition from "no authority epoch
// exists yet" to "authority epoch 1, revision 1 is ACTIVE," reusing every
// existing S1-S5 boundary exactly as ordinary rotation would:
// rotationcommit.CompleteGenesisCommit for the real Spanner Commit +
// signing boundary, gcswitness for the real GCS witness boundary, and
// epoch.TransitionOnCASOutcome/TransitionOnWitnessOutcome for the same
// fail-closed state machine every other transition already uses.
//
// What this package deliberately does NOT do: fabricate an
// acceptedRotationContext, a COMMITTED record, a Spanner commit timestamp,
// a witness record, or a revision/epoch history entry; insert a row or
// inject a signature outside the real Commit/Signer boundaries; retain any
// standing privilege beyond the lifetime of one ExecuteGenesis call; or
// resolve an ambiguous provider outcome by means of a later read. Every
// ambiguity fails closed to Outcome Unresolved, which callers MUST treat
// exactly like ADR-044's NEW_EPOCH_REQUIRED: manual review, never an
// automatic retry of the same identifiers.
//
// This package holds no direct Cloud KMS signing capability: its Signer
// dependency is rotationcommit.Signer, satisfied in production only by
// signerrpc.Client (see boundary_test.go), preserving the same two-process
// administrative separation ordinary rotation already requires (ADR-045
// §7, §15A). Dual control (Approval, two independent parties) and input
// validation (GenesisRequest) happen entirely before this file's
// ExecuteGenesis is ever reached; ExecuteGenesis itself never accepts a
// GenesisRequest that has not already passed NewGenesisRequest.
package bootstrap

import (
	"context"
	"errors"
	"fmt"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/epoch"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmsverifier"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/recovery"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
)

// GenesisSpannerClient is the minimal Spanner capability genesis needs
// beyond rotationcommit.RawCommitClient's single Commit RPC: obtaining a
// valid session to commit under. CreateSession has no ambiguous-outcome
// semantics to get wrong (unlike Commit, ClassifyCommit is never applied to
// it) -- a failure here always means "no mutation was ever attempted,"
// never "ambiguous." In production this is satisfied directly by the same
// raw spannerpb.SpannerClient stub spannercommit.Dial + spannerpb.NewSpannerClient
// already construct; bootstrap never introduces a second, separate Spanner
// connection type.
type GenesisSpannerClient interface {
	rotationcommit.RawCommitClient
	CreateSession(ctx context.Context, req *spannerpb.CreateSessionRequest, opts ...grpc.CallOption) (*spannerpb.Session, error)
}

// Dependencies is every production capability ExecuteGenesis needs. Every
// field is a narrow, already-existing S1-S5 interface -- this package
// introduces no new capability type of its own beyond GenesisSpannerClient
// above.
type Dependencies struct {
	Spanner     GenesisSpannerClient
	Witness     gcswitness.ImmutableWitness
	Signer      rotationcommit.Signer
	Lineage     recovery.ApprovedSigningLineage
	PinStore    keypinning.Store
	Ledger      compromiseledger.Ledger
	EvidenceDir string
}

// Outcome classifies the result of one ExecuteGenesis call.
type Outcome int

const (
	// OutcomeUnknown is the zero value -- never a real result.
	OutcomeUnknown Outcome = iota
	// OutcomeRejected means a validation or precondition check failed
	// before any provider (Spanner or GCS) mutation was attempted. Safe to
	// correct and retry with the same or a corrected GenesisRequest.
	OutcomeRejected
	// OutcomeCompleted means this call performed the real Commit, real
	// signing, and real witness write, and the epoch is now StateActive.
	OutcomeCompleted
	// OutcomeAlreadyCompleted means the deterministic witness key already
	// held this exact request's own prior, independently-verified output --
	// an idempotent retry of a previously successful genesis. No Spanner
	// mutation was attempted this call.
	OutcomeAlreadyCompleted
	// OutcomeConflict means the deterministic witness key already holds
	// content that does NOT match this request's expected binding. This
	// must never be treated as success and must never be overwritten;
	// it indicates a reused identifier or a configuration error and
	// requires manual investigation.
	OutcomeConflict
	// OutcomeUnresolved means a provider mutation was attempted (Spanner
	// Commit and/or GCS witness write) and its outcome could not be
	// established as a clean, unambiguous success. Per ADR-044 §8/§9, this
	// is the NEW_EPOCH_REQUIRED case: the epoch is
	// StateUnresolvablePreparedOperation, and this exact GenesisRequest
	// (same identifiers) must never be retried automatically -- a fresh
	// genesis attempt requires fresh identifiers (GenerateFreshIdentifiers)
	// and separate, governed review of what actually happened to the prior
	// attempt.
	OutcomeUnresolved
)

func (o Outcome) String() string {
	switch o {
	case OutcomeRejected:
		return "REJECTED"
	case OutcomeCompleted:
		return "COMPLETED"
	case OutcomeAlreadyCompleted:
		return "ALREADY_COMPLETED"
	case OutcomeConflict:
		return "CONFLICT"
	case OutcomeUnresolved:
		return "UNRESOLVED"
	default:
		return "UNKNOWN"
	}
}

var (
	ErrGenesisConflict   = errors.New("bootstrap: witness target holds conflicting genesis content; refusing to proceed")
	ErrGenesisUnresolved = errors.New("bootstrap: genesis outcome could not be established as unambiguous success; NEW_EPOCH_REQUIRED-style manual review required")
)

// ExecuteGenesis is the sole orchestration entry point this package
// exposes. req MUST already be the product of a successful NewGenesisRequest
// call (dual control already validated). now is the wall-clock time used
// only for evidence timestamps -- it does not gate any security decision
// already made inside NewGenesisRequest.
func ExecuteGenesis(ctx context.Context, deps Dependencies, req GenesisRequest, now time.Time) (Outcome, error) {
	startedAt := now.UTC()
	witnessKey := req.WitnessKey()

	alreadyExists, err := CheckWitnessPreconditions(ctx, WitnessPreconditions{Witness: deps.Witness}, witnessKey)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, err)
	}
	if alreadyExists {
		return handleExistingWitness(ctx, deps, req, startedAt, witnessKey)
	}

	if err := CheckSigningPreconditions(ctx, SigningPreconditions{
		Lineage:  deps.Lineage,
		PinStore: deps.PinStore,
		Ledger:   deps.Ledger,
		Signer:   deps.Signer,
	}, req.SigningKeyID); err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, err)
	}

	candidateBytes, err := genesisCandidateBytes(req)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, fmt.Errorf("bootstrap: encode genesis candidate: %w", err))
	}
	stateDigest := protocol.HashCanonical(protocol.DomainNewEpochGenesis, candidateBytes)
	candidateDigest := plainDigest(candidateBytes)

	mutations, err := GenesisMutations(req, stateDigest, candidateDigest)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, fmt.Errorf("bootstrap: build genesis mutations: %w", err))
	}

	session, err := deps.Spanner.CreateSession(ctx, &spannerpb.CreateSessionRequest{
		Database: req.SpannerDatabase,
		Session:  &spannerpb.Session{},
	})
	if err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, fmt.Errorf("bootstrap: create Spanner session: %w", err))
	}
	commitRequest := GenesisCommitRequest(session.GetName(), mutations)

	operation, err := rotation.NewFixedOperation(
		req.EnvironmentID, req.AuthorityEpoch, req.ResourceIncarnation, req.OperationID,
		GenesisPredecessorRevision, GenesisRevision, GenesisPredecessorDigest,
		candidateBytes, nil,
	)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeRejected, fmt.Errorf("bootstrap: build genesis operation: %w", err))
	}

	payload, classification, commitErr := rotationcommit.CompleteGenesisCommit(ctx, deps.Spanner, commitRequest, operation, deps.Signer)
	if commitErr != nil {
		resultState := epoch.TransitionOnCASOutcome(classification.Outcome)
		if resultState == epoch.StateActive {
			// UnambiguousNotCommitted: Spanner itself proved nothing
			// changed. Safe to retry the same GenesisRequest.
			return finish(deps, req, startedAt, OutcomeRejected, fmt.Errorf("%w: %v (classification reason %d)", commitErr, commitErr, classification.Reason))
		}
		return finishWithClassification(deps, req, startedAt, OutcomeUnresolved, classification, resultState,
			fmt.Errorf("%w: Spanner commit outcome %s: %v", ErrGenesisUnresolved, classification.Outcome, commitErr))
	}

	wireBytes, err := protocol.MarshalCommittedPayloadJSON(payload)
	if err != nil {
		return finishWithClassification(deps, req, startedAt, OutcomeUnresolved, classification, epoch.StateUnresolvablePreparedOperation,
			fmt.Errorf("%w: encode committed witness payload: %v", ErrGenesisUnresolved, err))
	}

	createOutcome, createErr := deps.Witness.CreateExactIfAbsent(ctx, witnessKey, wireBytes)
	witnessed := createOutcome == gcswitness.CreateSuccess || createOutcome == gcswitness.AlreadyExistsIdentical
	resultState := epoch.TransitionOnWitnessOutcome(witnessed)
	if !witnessed {
		reason := createErr
		if reason == nil {
			reason = fmt.Errorf("witness create outcome %s", createOutcome)
		}
		return finishGenesisWitnessed(deps, req, startedAt, OutcomeUnresolved, classification, createOutcome, resultState, stateDigest,
			fmt.Errorf("%w: GCS witness create outcome %s: %v", ErrGenesisUnresolved, createOutcome, reason))
	}

	return finishGenesisWitnessed(deps, req, startedAt, OutcomeCompleted, classification, createOutcome, resultState, stateDigest, nil)
}

// handleExistingWitness implements the S6 Phase 9 idempotency path: the
// deterministic witness key already holds content. It is independently
// re-verified against req's own expected binding -- never trusted merely
// because a byte string exists at the expected key -- before being treated
// as a successful, safe-to-report-idempotent prior genesis.
func handleExistingWitness(ctx context.Context, deps Dependencies, req GenesisRequest, startedAt time.Time, witnessKey string) (Outcome, error) {
	raw, err := deps.Witness.ReadExact(ctx, witnessKey)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeUnresolved, fmt.Errorf("%w: witness key reported present but unreadable: %v", ErrGenesisUnresolved, err))
	}
	payload, err := protocol.UnmarshalCommittedPayloadJSON(raw)
	if err != nil {
		return finish(deps, req, startedAt, OutcomeConflict, fmt.Errorf("%w: existing witness content is malformed: %v", ErrGenesisConflict, err))
	}

	expected := recovery.ExpectedBinding{
		EnvironmentID:       req.EnvironmentID,
		AuthorityEpoch:      req.AuthorityEpoch,
		ResourceIncarnation: req.ResourceIncarnation,
		OperationID:         req.OperationID,
		PredecessorRevision: GenesisPredecessorRevision,
		PredecessorDigest:   GenesisPredecessorDigest,
		ApprovedSigningLineage: func(keyID protocol.SigningKeyID) bool {
			return keyID == req.SigningKeyID
		},
	}
	if payload.RevisionNumber() != GenesisRevision || !payload.IsV2() {
		return finish(deps, req, startedAt, OutcomeConflict, fmt.Errorf("%w: existing witness content is not a matching V2 genesis record", ErrGenesisConflict))
	}

	verifier, verifierErr := kmsverifier.New(deps.PinStore, deps.Ledger)
	if verifierErr != nil {
		return finish(deps, req, startedAt, OutcomeUnresolved, fmt.Errorf("%w: cannot construct verifier to confirm prior genesis: %v", ErrGenesisUnresolved, verifierErr))
	}
	if err := recovery.VerifyPersistedCommitted(ctx, verifier, payload, expected); err != nil {
		return finish(deps, req, startedAt, OutcomeConflict, fmt.Errorf("%w: %v", ErrGenesisConflict, err))
	}

	return finish(deps, req, startedAt, OutcomeAlreadyCompleted, nil)
}

func finish(deps Dependencies, req GenesisRequest, startedAt time.Time, outcome Outcome, resultErr error) (Outcome, error) {
	completedAt := time.Now().UTC()
	evidence := evidenceFor(req, startedAt, completedAt, outcome.String())
	evidence.FinalEpochState = epoch.StateUnresolvablePreparedOperation.String()
	if outcome == OutcomeAlreadyCompleted {
		evidence.FinalEpochState = epoch.StateActive.String()
	}
	if resultErr != nil {
		evidence.FailureReason = resultErr.Error()
	}
	if writeErr := WriteEvidence(deps.EvidenceDir, evidence); writeErr != nil && !errors.Is(writeErr, ErrEvidenceAlreadyExists) {
		if resultErr != nil {
			return outcome, fmt.Errorf("%w (evidence write also failed: %v)", resultErr, writeErr)
		}
		return outcome, fmt.Errorf("bootstrap: write evidence: %w", writeErr)
	}
	return outcome, resultErr
}

func finishWithClassification(deps Dependencies, req GenesisRequest, startedAt time.Time, outcome Outcome, classification rotationcommit.CommitClassification, resultState epoch.State, resultErr error) (Outcome, error) {
	completedAt := time.Now().UTC()
	evidence := evidenceFor(req, startedAt, completedAt, outcome.String())
	evidence.CommitClassification = classification.Outcome.String()
	evidence.FinalEpochState = resultState.String()
	if resultErr != nil {
		evidence.FailureReason = resultErr.Error()
	}
	if writeErr := WriteEvidence(deps.EvidenceDir, evidence); writeErr != nil && !errors.Is(writeErr, ErrEvidenceAlreadyExists) {
		return outcome, fmt.Errorf("%w (evidence write also failed: %v)", resultErr, writeErr)
	}
	return outcome, resultErr
}

func finishGenesisWitnessed(deps Dependencies, req GenesisRequest, startedAt time.Time, outcome Outcome, classification rotationcommit.CommitClassification, createOutcome gcswitness.CreateOutcome, resultState epoch.State, stateDigest protocol.Digest32, resultErr error) (Outcome, error) {
	completedAt := time.Now().UTC()
	evidence := evidenceFor(req, startedAt, completedAt, outcome.String())
	evidence.CommitClassification = classification.Outcome.String()
	evidence.WitnessCreateOutcome = createOutcome.String()
	evidence.FinalEpochState = resultState.String()
	evidence.StateDigestHex = stateDigest.String()
	if resultErr != nil {
		evidence.FailureReason = resultErr.Error()
	}
	if writeErr := WriteEvidence(deps.EvidenceDir, evidence); writeErr != nil && !errors.Is(writeErr, ErrEvidenceAlreadyExists) {
		if resultErr != nil {
			return outcome, fmt.Errorf("%w (evidence write also failed: %v)", resultErr, writeErr)
		}
		return outcome, fmt.Errorf("bootstrap: write evidence: %w", writeErr)
	}
	return outcome, resultErr
}

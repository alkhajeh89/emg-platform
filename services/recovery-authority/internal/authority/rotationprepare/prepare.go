// Package rotationprepare is the production PREPARE/CAS layer ADR-044 §17
// item 1 records as missing ("the PREPARE/CAS orchestration layer above
// rotationcommit.completeRawCommit has deliberately not been built yet" --
// spannercommit's own package doc, and cmd/recovery-authority's own S5
// scope note). It builds the exact, real *spannerpb.CommitRequest an
// ordinary (non-genesis) authority rotation needs, by reading the current
// authority_head row inside the same real read-write transaction the
// eventual Commit will use, and independently comparing that row against
// the caller's declared candidate before ever agreeing the Commit may be
// attempted.
//
// This package deliberately does NOT call Commit itself, does NOT
// construct an acceptedRotationContext, and does NOT sign anything --
// those remain rotationcommit.CompleteRotationCommit's exclusive
// responsibility, unmodified by this package's existence. The separation
// is intentional and mirrors ADR-044 §6/§9's own governing principle: a
// later read must never be used to resolve Commit ambiguity. This
// package's read happens strictly BEFORE Commit is ever invoked -- it is
// pre-commit state acquisition, not post-commit classification, and it
// never runs after a Commit attempt of any kind.
package rotationprepare

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"fmt"
	"strconv"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotation"
)

// RotationSpannerClient is the minimal, narrow Spanner capability this
// package needs beyond rotationcommit.RawCommitClient's single Commit RPC:
// session creation, a real read-write transaction, one Read, and Rollback
// (to release the transaction/session cleanly when a candidate is refused
// before Commit is ever reached). It is satisfied directly, in production,
// by the same raw generated spannerpb.SpannerClient stub every other
// production Spanner boundary in this codebase already uses (spannercommit,
// bootstrap.GenesisSpannerClient) -- this package introduces no second
// Spanner connection type and no GAX/high-level transaction helper.
type RotationSpannerClient interface {
	CreateSession(ctx context.Context, req *spannerpb.CreateSessionRequest, opts ...grpc.CallOption) (*spannerpb.Session, error)
	BeginTransaction(ctx context.Context, req *spannerpb.BeginTransactionRequest, opts ...grpc.CallOption) (*spannerpb.Transaction, error)
	Read(ctx context.Context, req *spannerpb.ReadRequest, opts ...grpc.CallOption) (*spannerpb.ResultSet, error)
	Rollback(ctx context.Context, req *spannerpb.RollbackRequest, opts ...grpc.CallOption) (*emptypb.Empty, error)
}

// Candidate is the caller's fully-formed intent for one ordinary rotation
// attempt: everything rotation.NewFixedOperation needs except the proposed
// revision, which is always exactly ExpectedRevision+1 for an ordinary
// rotation (this package computes it, rather than accepting it as a
// separate, independently-forgeable input).
type Candidate struct {
	EnvironmentID       protocol.EnvironmentID
	AuthorityEpoch      protocol.AuthorityEpoch
	ResourceIncarnation protocol.ResourceIncarnationID
	OperationID         protocol.OperationID
	ExpectedRevision    protocol.RevisionNumber
	// PredecessorDigest is the state digest the caller believes the current
	// authority_head row already holds -- the value this rotation is
	// proposing to build on top of. It is compared against the row's own
	// state_digest column, read fresh inside this same transaction; it is
	// never trusted merely because the caller supplied it.
	PredecessorDigest protocol.Digest32
	CandidateBytes    []byte
	PreparedBytes     []byte
}

// PrepareResult is PrepareOrdinaryRotation's outcome. Exactly one of
// (Ready == true, CommitRequest != nil) or (Ready == false, Reason != "")
// holds -- there is no third state.
type PrepareResult struct {
	Ready bool
	// Reason explains why Commit must not be attempted, when Ready is
	// false. Never populated when Ready is true.
	Reason string

	Operation       rotation.FixedOperation
	CommitRequest   *spannerpb.CommitRequest
	SessionName     string
	TransactionID   []byte
	StateDigest     protocol.Digest32
	CandidateDigest protocol.Digest32
}

// ErrNoExistingAuthorityHead means the resource incarnation has no prior
// authority_head row at all -- ordinary rotation requires a prior genesis;
// it never creates the first row.
var ErrNoExistingAuthorityHead = errors.New("rotationprepare: no existing authority_head row for this resource incarnation")

var authorityHeadReadColumns = []string{
	"authority_epoch",
	"revision_number",
	"operation_id",
	"state_digest",
	"candidate_digest",
	"predecessor_checkpoint_digest",
	"commit_timestamp",
}

var (
	authorityHeadWriteColumns = []string{
		"environment_id", "resource_incarnation_id", "authority_epoch",
		"revision_number", "operation_id", "state_digest", "candidate_digest",
		"predecessor_checkpoint_digest", "commit_timestamp",
	}
	authorityTransitionHistoryColumns = []string{
		"environment_id", "resource_incarnation_id", "revision_number",
		"operation_id", "predecessor_revision", "authority_epoch",
		"state_digest", "candidate_digest", "commit_timestamp",
	}
)

const spannerCommitTimestampSentinel = "spanner.commit_timestamp()"

// PrepareOrdinaryRotation begins a real read-write transaction, reads the
// current authority_head row for (candidate.EnvironmentID,
// candidate.ResourceIncarnation), and either refuses to proceed (Ready ==
// false, Commit never attempted, transaction rolled back) or returns a
// fully-formed *spannerpb.CommitRequest ready for
// rotationcommit.CompleteRotationCommit -- never both, and never a
// CommitRequest built from anything other than this transaction's own real
// read.
func PrepareOrdinaryRotation(ctx context.Context, client RotationSpannerClient, database string, candidate Candidate) (PrepareResult, error) {
	session, err := client.CreateSession(ctx, &spannerpb.CreateSessionRequest{
		Database: database,
		Session:  &spannerpb.Session{},
	})
	if err != nil {
		return PrepareResult{}, fmt.Errorf("rotationprepare: create session: %w", err)
	}

	txn, err := client.BeginTransaction(ctx, &spannerpb.BeginTransactionRequest{
		Session: session.GetName(),
		Options: &spannerpb.TransactionOptions{
			Mode: &spannerpb.TransactionOptions_ReadWrite_{
				ReadWrite: &spannerpb.TransactionOptions_ReadWrite{},
			},
		},
	})
	if err != nil {
		return PrepareResult{}, fmt.Errorf("rotationprepare: begin transaction: %w", err)
	}
	txnID := txn.GetId()

	row, found, err := readAuthorityHead(ctx, client, session.GetName(), txnID, candidate.EnvironmentID.String(), candidate.ResourceIncarnation.String())
	if err != nil {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{}, fmt.Errorf("rotationprepare: read authority_head: %w", err)
	}
	if !found {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{Ready: false, Reason: ErrNoExistingAuthorityHead.Error()}, nil
	}

	if reason := candidate.checkAgainst(row); reason != "" {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{Ready: false, Reason: reason}, nil
	}

	proposedRevision := protocol.NewRevisionNumber(candidate.ExpectedRevision.Uint64() + 1)
	operation, err := rotation.NewFixedOperation(
		candidate.EnvironmentID, candidate.AuthorityEpoch, candidate.ResourceIncarnation, candidate.OperationID,
		candidate.ExpectedRevision, proposedRevision, candidate.PredecessorDigest,
		candidate.CandidateBytes, candidate.PreparedBytes,
	)
	if err != nil {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{}, fmt.Errorf("rotationprepare: build fixed operation: %w", err)
	}

	stateDigest := protocol.HashCanonical(protocol.DomainRotationCandidate, operation.CandidateBytes())
	candidateDigest, err := plainDigest(operation.CandidateBytes())
	if err != nil {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{}, fmt.Errorf("rotationprepare: candidate digest: %w", err)
	}

	mutations, err := rotationMutations(operation, stateDigest, candidateDigest)
	if err != nil {
		rollback(ctx, client, session.GetName(), txnID)
		return PrepareResult{}, fmt.Errorf("rotationprepare: build mutations: %w", err)
	}

	request := &spannerpb.CommitRequest{
		Session:     session.GetName(),
		Transaction: &spannerpb.CommitRequest_TransactionId{TransactionId: txnID},
		Mutations:   mutations,
	}
	return PrepareResult{
		Ready:           true,
		Operation:       operation,
		CommitRequest:   request,
		SessionName:     session.GetName(),
		TransactionID:   txnID,
		StateDigest:     stateDigest,
		CandidateDigest: candidateDigest,
	}, nil
}

// checkAgainst reports, as a non-empty human-readable reason, the first
// mismatch found between candidate and the freshly-read authority_head row
// -- or "" if every check passes. Every check is independent and mandatory;
// none is skipped because another already failed differently, but only the
// first-detected reason is reported (this package refuses to proceed on
// any single mismatch, so which one is named first has no security
// consequence).
func (candidate Candidate) checkAgainst(row headSnapshot) string {
	if row.revisionNumber != candidate.ExpectedRevision.Uint64() {
		return fmt.Sprintf("stale expected revision: candidate expected %d, authority_head is at %d", candidate.ExpectedRevision.Uint64(), row.revisionNumber)
	}
	if row.authorityEpoch != candidate.AuthorityEpoch.String() {
		return fmt.Sprintf("authority epoch mismatch: candidate declared %q, authority_head has %q", candidate.AuthorityEpoch.String(), row.authorityEpoch)
	}
	if row.stateDigest != candidate.PredecessorDigest {
		return "predecessor digest mismatch: candidate's declared predecessor digest does not match authority_head's current state_digest"
	}
	return ""
}

type headSnapshot struct {
	authorityEpoch string
	revisionNumber uint64
	operationID    string
	stateDigest    protocol.Digest32
}

func readAuthorityHead(ctx context.Context, client RotationSpannerClient, sessionName string, transactionID []byte, environmentID, resourceIncarnationID string) (headSnapshot, bool, error) {
	key, err := structpb.NewList([]interface{}{environmentID, resourceIncarnationID})
	if err != nil {
		return headSnapshot{}, false, err
	}
	result, err := client.Read(ctx, &spannerpb.ReadRequest{
		Session:     sessionName,
		Transaction: &spannerpb.TransactionSelector{Selector: &spannerpb.TransactionSelector_Id{Id: transactionID}},
		Table:       "authority_head",
		Columns:     authorityHeadReadColumns,
		KeySet:      &spannerpb.KeySet{Keys: []*structpb.ListValue{key}},
	})
	if err != nil {
		return headSnapshot{}, false, err
	}
	if len(result.GetRows()) == 0 {
		return headSnapshot{}, false, nil
	}
	values := result.GetRows()[0].GetValues()
	if len(values) != len(authorityHeadReadColumns) {
		return headSnapshot{}, false, fmt.Errorf("unexpected column count: got %d, want %d", len(values), len(authorityHeadReadColumns))
	}
	revision, err := strconv.ParseUint(values[1].GetStringValue(), 10, 64)
	if err != nil {
		return headSnapshot{}, false, fmt.Errorf("decode revision_number: %w", err)
	}
	stateDigest, err := decodeDigest(values[3])
	if err != nil {
		return headSnapshot{}, false, fmt.Errorf("decode state_digest: %w", err)
	}
	return headSnapshot{
		authorityEpoch: values[0].GetStringValue(),
		revisionNumber: revision,
		operationID:    values[2].GetStringValue(),
		stateDigest:    stateDigest,
	}, true, nil
}

func decodeDigest(value *structpb.Value) (protocol.Digest32, error) {
	raw, err := base64.StdEncoding.DecodeString(value.GetStringValue())
	if err != nil {
		return protocol.Digest32{}, err
	}
	return protocol.NewDigest32(raw)
}

func base64Digest(digest protocol.Digest32) string {
	return base64.StdEncoding.EncodeToString(digest.Bytes())
}

// plainDigest computes an undomained SHA-256 of data for the purely
// observational authority_transition_history.candidate_digest column,
// exactly mirroring bootstrap.plainDigest's own reasoning: reusing
// protocol.DomainRotationCandidate here (the security-meaningful state
// digest) would make this column bit-identical to stateDigest for the same
// bytes, collapsing a distinction domain separation exists to preserve.
func plainDigest(data []byte) (protocol.Digest32, error) {
	sum := sha256.Sum256(data)
	return protocol.NewDigest32(sum[:])
}

// rotationMutations builds the two mutations one ordinary rotation Commit
// writes: an InsertOrUpdate of authority_head (unlike genesis's Insert-only
// authority_head write -- an ordinary rotation legitimately updates the
// existing row) and an Insert (never InsertOrUpdate) of
// authority_transition_history, whose primary key includes revision_number
// -- so a duplicate/stale attempt at an already-advanced revision fails
// closed at the Spanner layer even if this package's own pre-commit check
// were somehow bypassed (defense in depth, mirroring bootstrap.GenesisMutations's
// own reasoning).
func rotationMutations(operation rotation.FixedOperation, stateDigest, candidateDigest protocol.Digest32) ([]*spannerpb.Mutation, error) {
	headValues, err := structpb.NewList([]interface{}{
		operation.EnvironmentID().String(),
		operation.ResourceIncarnation().String(),
		operation.AuthorityEpoch().String(),
		strconv.FormatUint(operation.ProposedRevision().Uint64(), 10),
		operation.OperationID().String(),
		base64Digest(stateDigest),
		base64Digest(candidateDigest),
		base64Digest(operation.PreparedDigest()),
		spannerCommitTimestampSentinel,
	})
	if err != nil {
		return nil, err
	}
	historyValues, err := structpb.NewList([]interface{}{
		operation.EnvironmentID().String(),
		operation.ResourceIncarnation().String(),
		strconv.FormatUint(operation.ProposedRevision().Uint64(), 10),
		operation.OperationID().String(),
		strconv.FormatUint(operation.ExpectedRevision().Uint64(), 10),
		operation.AuthorityEpoch().String(),
		base64Digest(stateDigest),
		base64Digest(candidateDigest),
		spannerCommitTimestampSentinel,
	})
	if err != nil {
		return nil, err
	}
	return []*spannerpb.Mutation{
		{Operation: &spannerpb.Mutation_InsertOrUpdate{InsertOrUpdate: &spannerpb.Mutation_Write{
			Table:   "authority_head",
			Columns: authorityHeadWriteColumns,
			Values:  []*structpb.ListValue{headValues},
		}}},
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table:   "authority_transition_history",
			Columns: authorityTransitionHistoryColumns,
			Values:  []*structpb.ListValue{historyValues},
		}}},
	}, nil
}

// rollback releases the transaction/session's lock as a best-effort cleanup
// when this package decides, before ever calling Commit, that a candidate
// must be refused. Its error is deliberately discarded: a failed Rollback
// here never changes the fact that Commit was never invoked (Reason is
// already set), and this package has no retry or escalation logic of its
// own to apply to a Rollback failure -- the same best-effort convention
// rotationcommit's own emulator test helpers already use.
func rollback(ctx context.Context, client RotationSpannerClient, sessionName string, transactionID []byte) {
	_, _ = client.Rollback(ctx, &spannerpb.RollbackRequest{Session: sessionName, TransactionId: transactionID})
}

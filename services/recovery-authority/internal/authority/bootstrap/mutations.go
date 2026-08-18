package bootstrap

import (
	"crypto/sha256"
	"encoding/base64"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// plainDigest computes an undomained SHA-256 of data, deliberately NEVER
// using protocol.HashCanonical with any existing DomainSeparator: reusing,
// say, DomainRotationCandidate here would make this purely-observational
// authority_transition_history.candidate_digest column bit-identical to
// what an ordinary rotation's cryptographically meaningful stateDigest
// would be for the same bytes -- exactly the cross-record-family confusion
// domain separation exists to prevent. This value is never signed, never
// verified, and never appears in any CommittedPayload; it exists solely so
// an operator reading the Spanner row can cross-reference it against the
// genesis candidate content recorded in evidence.
func plainDigest(data []byte) protocol.Digest32 {
	sum := sha256.Sum256(data)
	digest, err := protocol.NewDigest32(sum[:])
	if err != nil {
		panic("sha256 returned a non-32-byte digest")
	}
	return digest
}

// authorityHeadColumns and authorityTransitionHistoryColumns mirror,
// column-for-column, the only schema definition this codebase has ever
// agreed on for these two tables: scripts/emulator/schema.sql (whose own
// column names are independently echoed by
// conformance/spanneradapter.TransitionMutations and by epoch/state.go's
// doc comments). No production DDL/migration for these tables exists yet
// (S4's finding: no executable GCP IaC framework) -- this is a genuine
// real-Spanner qualification gap, reported in the S6 final report, not
// something this package can close by writing a migration file
// unilaterally.
var (
	authorityHeadColumns = []string{
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

// spannerCommitTimestampSentinel is Cloud Spanner's documented pending
// commit-timestamp value for a column declared
// `OPTIONS (allow_commit_timestamp = true)`. It is never a real value this
// package invents meaning for -- Spanner substitutes the TrueTime-assigned
// value at commit.
const spannerCommitTimestampSentinel = "spanner.commit_timestamp()"

func base64Digest(digest protocol.Digest32) string {
	return base64.StdEncoding.EncodeToString(digest.Bytes())
}

// GenesisMutations builds the two Insert (never InsertOrUpdate) mutations a
// genesis Commit writes: one new authority_head row and one new
// authority_transition_history row. Both use Mutation_Insert specifically
// --  unlike an ordinary rotation's authority_head InsertOrUpdate -- because
// a genesis attempt must never legitimately update an existing head row;
// any conflict at the Spanner layer must surface as an error (S6 Phase 4/9,
// defense-in-depth alongside the pre-commit witness-existence idempotency
// check in ExecuteGenesis). candidateDigest is a plain, non-domain-separated
// SHA-256 of the raw candidate bytes, recorded for operator observability
// only; the security-critical digest is stateDigest, computed the same way
// rotationcommit's genesis path computes it
// (protocol.HashCanonical(protocol.DomainNewEpochGenesis, ...)) and
// embedded in the signed CommittedPayload independently of this function.
func GenesisMutations(req GenesisRequest, stateDigest, candidateDigest protocol.Digest32) ([]*spannerpb.Mutation, error) {
	headValues, err := structpb.NewList([]interface{}{
		req.EnvironmentID.String(),
		req.ResourceIncarnation.String(),
		req.AuthorityEpoch.String(),
		GenesisRevision.String(),
		req.OperationID.String(),
		base64Digest(stateDigest),
		base64Digest(candidateDigest),
		base64Digest(GenesisPredecessorDigest),
		spannerCommitTimestampSentinel,
	})
	if err != nil {
		return nil, err
	}
	historyValues, err := structpb.NewList([]interface{}{
		req.EnvironmentID.String(),
		req.ResourceIncarnation.String(),
		GenesisRevision.String(),
		req.OperationID.String(),
		GenesisPredecessorRevision.String(),
		req.AuthorityEpoch.String(),
		base64Digest(stateDigest),
		base64Digest(candidateDigest),
		spannerCommitTimestampSentinel,
	})
	if err != nil {
		return nil, err
	}
	return []*spannerpb.Mutation{
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table:   "authority_head",
			Columns: authorityHeadColumns,
			Values:  []*structpb.ListValue{headValues},
		}}},
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table:   "authority_transition_history",
			Columns: authorityTransitionHistoryColumns,
			Values:  []*structpb.ListValue{historyValues},
		}}},
	}, nil
}

// GenesisCommitRequest wraps mutations in a CommitRequest using a
// SingleUseTransaction (ReadWrite mode): genesis has no prior state to
// read within the same transaction (there is nothing to CAS against), so a
// single-use transaction -- begin and commit in the same RPC -- is the
// correct, simplest choice, and it is why bootstrap's Spanner dependency
// (see genesis.go's GenesisSpannerClient) needs CreateSession but never
// BeginTransaction.
func GenesisCommitRequest(sessionName string, mutations []*spannerpb.Mutation) *spannerpb.CommitRequest {
	return &spannerpb.CommitRequest{
		Session: sessionName,
		Transaction: &spannerpb.CommitRequest_SingleUseTransaction{
			SingleUseTransaction: &spannerpb.TransactionOptions{
				Mode: &spannerpb.TransactionOptions_ReadWrite_{
					ReadWrite: &spannerpb.TransactionOptions_ReadWrite{},
				},
			},
		},
		Mutations: mutations,
	}
}

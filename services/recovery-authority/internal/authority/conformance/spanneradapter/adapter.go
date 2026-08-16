// Package spanneradapter is a TEST/EMULATOR-ONLY raw gRPC Spanner client
// used exclusively to exercise ADR-043's frozen commit-classification logic
// against the official Cloud Spanner emulator. It is not a production
// adapter: nothing in this package is wired into any runtime path, and it
// is imported only from _test.go files gated behind the "emulator" build
// tag.
//
// It uses only cloud.google.com/go/spanner/apiv1/spannerpb.SpannerClient --
// the same raw generated stub rotationcommit.RawCommitClient already
// requires. It never uses cloud.google.com/go/spanner.Client,
// ReadWriteTransaction, Apply, or any GAX convenience helper. Sessions are
// regular (non-multiplexed); no Commit call is retried by this package.
package spanneradapter

import (
	"context"
	"encoding/base64"
	"fmt"
	"strconv"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/protobuf/types/known/structpb"
)

// Dial opens an insecure gRPC connection to the Cloud Spanner emulator at
// addr (e.g. "localhost:9010"). The emulator does not check credentials;
// this dial option is never valid against a real Spanner endpoint, which is
// exactly why this package is confined to emulator-tier tests.
func Dial(ctx context.Context, addr string) (*grpc.ClientConn, error) {
	return grpc.NewClient(addr, grpc.WithTransportCredentials(insecure.NewCredentials()))
}

// Client is a thin, uninstrumented wrapper over the raw generated stub. Its
// Commit method is never called directly by test code -- tests pass
// c.Raw() (or an InstrumentedCommitClient wrapping it) straight into
// rotationcommit's unexported completeRawCommit, so the exact production
// code path is exercised, not a reimplementation of it.
type Client struct {
	raw      spannerpb.SpannerClient
	database string
}

func New(conn *grpc.ClientConn, database string) *Client {
	return &Client{raw: spannerpb.NewSpannerClient(conn), database: database}
}

// Raw returns the underlying generated stub. Its Commit method signature is
// identical to rotationcommit.RawCommitClient, so it can be passed there
// directly.
func (c *Client) Raw() spannerpb.SpannerClient { return c.raw }

func (c *Client) CreateSession(ctx context.Context) (string, error) {
	session, err := c.raw.CreateSession(ctx, &spannerpb.CreateSessionRequest{
		Database: c.database,
		Session:  &spannerpb.Session{},
	})
	if err != nil {
		return "", fmt.Errorf("create session: %w", err)
	}
	return session.GetName(), nil
}

func (c *Client) DeleteSession(ctx context.Context, sessionName string) error {
	_, err := c.raw.DeleteSession(ctx, &spannerpb.DeleteSessionRequest{Name: sessionName})
	return err
}

// BeginReadWrite starts a real read-write transaction. This is the manual,
// raw-stub equivalent of what ReadWriteTransaction would otherwise hide --
// used here, and only here, because the task authorization explicitly
// requires exercising real transaction/conflict behavior at this tier.
func (c *Client) BeginReadWrite(ctx context.Context, sessionName string) ([]byte, error) {
	txn, err := c.raw.BeginTransaction(ctx, &spannerpb.BeginTransactionRequest{
		Session: sessionName,
		Options: &spannerpb.TransactionOptions{
			Mode: &spannerpb.TransactionOptions_ReadWrite_{
				ReadWrite: &spannerpb.TransactionOptions_ReadWrite{},
			},
		},
	})
	if err != nil {
		return nil, fmt.Errorf("begin transaction: %w", err)
	}
	return txn.GetId(), nil
}

func (c *Client) Rollback(ctx context.Context, sessionName string, transactionID []byte) error {
	_, err := c.raw.Rollback(ctx, &spannerpb.RollbackRequest{
		Session:       sessionName,
		TransactionId: transactionID,
	})
	return err
}

// AuthorityHeadRow is the emulator-schema mirror of one authority_head row.
type AuthorityHeadRow struct {
	AuthorityEpoch              string
	RevisionNumber              uint64
	OperationID                 string
	StateDigest                 protocol.Digest32
	CandidateDigest             protocol.Digest32
	PredecessorCheckpointDigest protocol.Digest32
	CommitTimestamp             time.Time
}

var authorityHeadColumns = []string{
	"authority_epoch",
	"revision_number",
	"operation_id",
	"state_digest",
	"candidate_digest",
	"predecessor_checkpoint_digest",
	"commit_timestamp",
}

// ReadAuthorityHead performs a real Read RPC inside the given transaction.
// found is false when no row exists yet for this (environment, resource
// incarnation) pair -- the legitimate "first rotation" case.
func (c *Client) ReadAuthorityHead(
	ctx context.Context,
	sessionName string,
	transactionID []byte,
	environmentID, resourceIncarnationID string,
) (AuthorityHeadRow, bool, error) {
	key, err := structpb.NewList([]interface{}{environmentID, resourceIncarnationID})
	if err != nil {
		return AuthorityHeadRow{}, false, err
	}
	result, err := c.raw.Read(ctx, &spannerpb.ReadRequest{
		Session:     sessionName,
		Transaction: &spannerpb.TransactionSelector{Selector: &spannerpb.TransactionSelector_Id{Id: transactionID}},
		Table:       "authority_head",
		Columns:     authorityHeadColumns,
		KeySet:      &spannerpb.KeySet{Keys: []*structpb.ListValue{key}},
	})
	if err != nil {
		return AuthorityHeadRow{}, false, fmt.Errorf("read authority_head: %w", err)
	}
	if len(result.GetRows()) == 0 {
		return AuthorityHeadRow{}, false, nil
	}
	row, err := decodeAuthorityHeadRow(result.GetRows()[0])
	if err != nil {
		return AuthorityHeadRow{}, false, err
	}
	return row, true, nil
}

func decodeAuthorityHeadRow(values *structpb.ListValue) (AuthorityHeadRow, error) {
	v := values.GetValues()
	if len(v) != len(authorityHeadColumns) {
		return AuthorityHeadRow{}, fmt.Errorf("unexpected column count: got %d, want %d", len(v), len(authorityHeadColumns))
	}
	revision, err := strconv.ParseUint(v[1].GetStringValue(), 10, 64)
	if err != nil {
		return AuthorityHeadRow{}, fmt.Errorf("decode revision_number: %w", err)
	}
	stateDigest, err := decodeDigest(v[3])
	if err != nil {
		return AuthorityHeadRow{}, fmt.Errorf("decode state_digest: %w", err)
	}
	candidateDigest, err := decodeDigest(v[4])
	if err != nil {
		return AuthorityHeadRow{}, fmt.Errorf("decode candidate_digest: %w", err)
	}
	predecessorDigest, err := decodeDigest(v[5])
	if err != nil {
		return AuthorityHeadRow{}, fmt.Errorf("decode predecessor_checkpoint_digest: %w", err)
	}
	commitTimestamp, err := time.Parse(time.RFC3339Nano, v[6].GetStringValue())
	if err != nil {
		return AuthorityHeadRow{}, fmt.Errorf("decode commit_timestamp: %w", err)
	}
	return AuthorityHeadRow{
		AuthorityEpoch:              v[0].GetStringValue(),
		RevisionNumber:              revision,
		OperationID:                 v[2].GetStringValue(),
		StateDigest:                 stateDigest,
		CandidateDigest:             candidateDigest,
		PredecessorCheckpointDigest: predecessorDigest,
		CommitTimestamp:             commitTimestamp,
	}, nil
}

func decodeDigest(value *structpb.Value) (protocol.Digest32, error) {
	raw, err := base64.StdEncoding.DecodeString(value.GetStringValue())
	if err != nil {
		return protocol.Digest32{}, err
	}
	return protocol.NewDigest32(raw)
}

// TransitionMutations is what a rotation-writer harness would build
// application-side, in the same session/transaction as a real Read, before
// invoking the real (never-retried) Commit RPC. Building this is
// necessarily new harness code -- it does not exist in production, because
// the PREPARE/CAS orchestration layer above rotationcommit.completeRawCommit
// has deliberately not been built yet (out of scope for both this task and
// the prior one). It exists here only to produce genuine CommitRequest
// traffic against the emulator.
func TransitionMutations(
	environmentID, resourceIncarnationID, authorityEpoch, operationID string,
	revisionNumber, predecessorRevision uint64,
	stateDigest, candidateDigest, predecessorCheckpointDigest protocol.Digest32,
) []*spannerpb.Mutation {
	headValues, err := structpb.NewList([]interface{}{
		environmentID,
		resourceIncarnationID,
		authorityEpoch,
		strconv.FormatUint(revisionNumber, 10),
		operationID,
		base64.StdEncoding.EncodeToString(stateDigest.Bytes()),
		base64.StdEncoding.EncodeToString(candidateDigest.Bytes()),
		base64.StdEncoding.EncodeToString(predecessorCheckpointDigest.Bytes()),
		"spanner.commit_timestamp()",
	})
	if err != nil {
		panic(err) // all inputs are static Go types; NewList cannot fail here
	}
	historyValues, err := structpb.NewList([]interface{}{
		environmentID,
		resourceIncarnationID,
		strconv.FormatUint(revisionNumber, 10),
		operationID,
		strconv.FormatUint(predecessorRevision, 10),
		authorityEpoch,
		base64.StdEncoding.EncodeToString(stateDigest.Bytes()),
		base64.StdEncoding.EncodeToString(candidateDigest.Bytes()),
		"spanner.commit_timestamp()",
	})
	if err != nil {
		panic(err)
	}
	return []*spannerpb.Mutation{
		{Operation: &spannerpb.Mutation_InsertOrUpdate{InsertOrUpdate: &spannerpb.Mutation_Write{
			Table: "authority_head",
			Columns: []string{
				"environment_id", "resource_incarnation_id", "authority_epoch",
				"revision_number", "operation_id", "state_digest", "candidate_digest",
				"predecessor_checkpoint_digest", "commit_timestamp",
			},
			Values: []*structpb.ListValue{headValues},
		}}},
		{Operation: &spannerpb.Mutation_Insert{Insert: &spannerpb.Mutation_Write{
			Table: "authority_transition_history",
			Columns: []string{
				"environment_id", "resource_incarnation_id", "revision_number",
				"operation_id", "predecessor_revision", "authority_epoch",
				"state_digest", "candidate_digest", "commit_timestamp",
			},
			Values: []*structpb.ListValue{historyValues},
		}}},
	}
}

func CommitRequest(sessionName string, transactionID []byte, mutations []*spannerpb.Mutation) *spannerpb.CommitRequest {
	return &spannerpb.CommitRequest{
		Session:     sessionName,
		Transaction: &spannerpb.CommitRequest_TransactionId{TransactionId: transactionID},
		Mutations:   mutations,
	}
}

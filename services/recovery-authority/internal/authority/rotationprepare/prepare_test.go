package rotationprepare

import (
	"context"
	"encoding/base64"
	"strconv"
	"testing"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
	"google.golang.org/protobuf/types/known/emptypb"
	"google.golang.org/protobuf/types/known/structpb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// fakeClient is a deterministic, in-memory double for RotationSpannerClient.
// It exists only to exercise this package's own decision logic in isolation
// -- it is never used to claim anything about real Cloud Spanner behavior
// (that is the emulator/real-cloud tiers' job).
type fakeClient struct {
	row           *fakeRow
	rollbackCalls int
	readErr       error
}

type fakeRow struct {
	authorityEpoch string
	revisionNumber uint64
	operationID    string
	stateDigest    protocol.Digest32
}

func (f *fakeClient) CreateSession(ctx context.Context, req *spannerpb.CreateSessionRequest, opts ...grpc.CallOption) (*spannerpb.Session, error) {
	return &spannerpb.Session{Name: "projects/p/instances/i/databases/d/sessions/s1"}, nil
}

func (f *fakeClient) BeginTransaction(ctx context.Context, req *spannerpb.BeginTransactionRequest, opts ...grpc.CallOption) (*spannerpb.Transaction, error) {
	return &spannerpb.Transaction{Id: []byte("txn-1")}, nil
}

func (f *fakeClient) Read(ctx context.Context, req *spannerpb.ReadRequest, opts ...grpc.CallOption) (*spannerpb.ResultSet, error) {
	if f.readErr != nil {
		return nil, f.readErr
	}
	if f.row == nil {
		return &spannerpb.ResultSet{}, nil
	}
	values, err := structpb.NewList([]interface{}{
		f.row.authorityEpoch,
		strconv.FormatUint(f.row.revisionNumber, 10),
		f.row.operationID,
		base64.StdEncoding.EncodeToString(f.row.stateDigest.Bytes()),
		base64.StdEncoding.EncodeToString(f.row.stateDigest.Bytes()),
		base64.StdEncoding.EncodeToString(f.row.stateDigest.Bytes()),
		"2026-01-01T00:00:00Z",
	})
	if err != nil {
		return nil, err
	}
	return &spannerpb.ResultSet{Rows: []*structpb.ListValue{values}}, nil
}

func (f *fakeClient) Rollback(ctx context.Context, req *spannerpb.RollbackRequest, opts ...grpc.CallOption) (*emptypb.Empty, error) {
	f.rollbackCalls++
	return &emptypb.Empty{}, nil
}

func testDigest(t *testing.T, seed byte) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = seed
	}
	digest, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func testCandidate(t *testing.T, expectedRevision uint64, predecessorDigest protocol.Digest32) Candidate {
	t.Helper()
	env, err := protocol.NewEnvironmentID("staging")
	if err != nil {
		t.Fatal(err)
	}
	epoch, err := protocol.NewAuthorityEpoch("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1")
	if err != nil {
		t.Fatal(err)
	}
	resource, err := protocol.NewResourceIncarnationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a2")
	if err != nil {
		t.Fatal(err)
	}
	operationID, err := protocol.NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3")
	if err != nil {
		t.Fatal(err)
	}
	return Candidate{
		EnvironmentID:       env,
		AuthorityEpoch:      epoch,
		ResourceIncarnation: resource,
		OperationID:         operationID,
		ExpectedRevision:    protocol.NewRevisionNumber(expectedRevision),
		PredecessorDigest:   predecessorDigest,
		CandidateBytes:      []byte("candidate-bytes"),
		PreparedBytes:       []byte("prepared-bytes"),
	}
}

// TestPrepareReadyOnMatch is the positive case: a row whose revision,
// epoch, and state digest all match the candidate's declared expectations
// produces a ready CommitRequest.
func TestPrepareReadyOnMatch(t *testing.T) {
	digest := testDigest(t, 7)
	candidate := testCandidate(t, 3, digest)
	client := &fakeClient{row: &fakeRow{
		authorityEpoch: candidate.AuthorityEpoch.String(),
		revisionNumber: 3,
		operationID:    "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a9",
		stateDigest:    digest,
	}}
	result, err := PrepareOrdinaryRotation(context.Background(), client, "db", candidate)
	if err != nil {
		t.Fatal(err)
	}
	if !result.Ready {
		t.Fatalf("expected Ready, got Reason=%q", result.Reason)
	}
	if result.CommitRequest == nil {
		t.Fatal("expected a non-nil CommitRequest when Ready")
	}
	if result.Operation.ProposedRevision().Uint64() != 4 {
		t.Fatalf("proposed revision = %d, want 4", result.Operation.ProposedRevision().Uint64())
	}
	if client.rollbackCalls != 0 {
		t.Fatalf("rollback must not be called on the ready path, got %d calls", client.rollbackCalls)
	}
}

// TestPrepareRefusesOnStaleRevision is Attack B: a candidate whose expected
// revision does not match the real row must never produce a CommitRequest.
func TestPrepareRefusesOnStaleRevision(t *testing.T) {
	digest := testDigest(t, 7)
	candidate := testCandidate(t, 3, digest)
	client := &fakeClient{row: &fakeRow{
		authorityEpoch: candidate.AuthorityEpoch.String(),
		revisionNumber: 4, // one ahead of what the candidate expects
		operationID:    "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a9",
		stateDigest:    digest,
	}}
	result, err := PrepareOrdinaryRotation(context.Background(), client, "db", candidate)
	if err != nil {
		t.Fatal(err)
	}
	if result.Ready {
		t.Fatal("must never be Ready on a stale expected revision")
	}
	if result.CommitRequest != nil {
		t.Fatal("must never produce a CommitRequest on a stale expected revision")
	}
	if client.rollbackCalls != 1 {
		t.Fatalf("expected exactly one rollback, got %d", client.rollbackCalls)
	}
}

// TestPrepareRefusesOnPredecessorDigestMismatch is Attack D.
func TestPrepareRefusesOnPredecessorDigestMismatch(t *testing.T) {
	rowDigest := testDigest(t, 7)
	candidateDigest := testDigest(t, 8) // different from the row's real state_digest
	candidate := testCandidate(t, 3, candidateDigest)
	client := &fakeClient{row: &fakeRow{
		authorityEpoch: candidate.AuthorityEpoch.String(),
		revisionNumber: 3,
		operationID:    "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a9",
		stateDigest:    rowDigest,
	}}
	result, err := PrepareOrdinaryRotation(context.Background(), client, "db", candidate)
	if err != nil {
		t.Fatal(err)
	}
	if result.Ready {
		t.Fatal("must never be Ready on a predecessor digest mismatch")
	}
}

// TestPrepareRefusesOnEpochMismatch is Attack F.
func TestPrepareRefusesOnEpochMismatch(t *testing.T) {
	digest := testDigest(t, 7)
	candidate := testCandidate(t, 3, digest)
	client := &fakeClient{row: &fakeRow{
		authorityEpoch: "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7ff", // a different, well-formed epoch
		revisionNumber: 3,
		operationID:    "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a9",
		stateDigest:    digest,
	}}
	result, err := PrepareOrdinaryRotation(context.Background(), client, "db", candidate)
	if err != nil {
		t.Fatal(err)
	}
	if result.Ready {
		t.Fatal("must never be Ready on an authority epoch mismatch")
	}
}

// TestPrepareRefusesWhenNoExistingRow proves ordinary rotation never
// silently behaves like a genesis: absence of a row is refused, not
// promoted to a first-row insert.
func TestPrepareRefusesWhenNoExistingRow(t *testing.T) {
	candidate := testCandidate(t, 0, protocol.Digest32{})
	client := &fakeClient{row: nil}
	result, err := PrepareOrdinaryRotation(context.Background(), client, "db", candidate)
	if err != nil {
		t.Fatal(err)
	}
	if result.Ready {
		t.Fatal("must never be Ready when no authority_head row exists")
	}
	if result.Reason != ErrNoExistingAuthorityHead.Error() {
		t.Fatalf("Reason = %q, want %q", result.Reason, ErrNoExistingAuthorityHead.Error())
	}
}

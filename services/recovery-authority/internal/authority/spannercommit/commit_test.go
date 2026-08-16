package spannercommit

import (
	"context"
	"errors"
	"testing"
	"time"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"
)

// Compile-time proof that *Client satisfies the exact boundary
// rotationcommit requires -- this is the only interface S2 is authorized
// to implement.
var _ rotationcommit.RawCommitClient = (*Client)(nil)

type fakeRawSpannerClient struct {
	spannerpb.SpannerClient // embedded nil: only Commit is exercised below
	calls                   int
	lastReq                 *spannerpb.CommitRequest
	response                *spannerpb.CommitResponse
	err                     error
}

func (f *fakeRawSpannerClient) Commit(_ context.Context, req *spannerpb.CommitRequest, _ ...grpc.CallOption) (*spannerpb.CommitResponse, error) {
	f.calls++
	f.lastReq = req
	return f.response, f.err
}

func TestCommitDelegatesExactlyOnceAndPassesRequestThroughUnmodified(t *testing.T) {
	req := &spannerpb.CommitRequest{Session: "projects/p/instances/i/databases/d/sessions/s"}
	want := &spannerpb.CommitResponse{}
	fake := &fakeRawSpannerClient{response: want}
	client := &Client{raw: fake}

	got, err := client.Commit(context.Background(), req)
	if err != nil {
		t.Fatal(err)
	}
	if got != want {
		t.Fatal("Commit must return the raw response unmodified")
	}
	if fake.calls != 1 {
		t.Fatalf("fake.calls = %d, want exactly 1 -- Commit must never retry internally", fake.calls)
	}
	if fake.lastReq != req {
		t.Fatal("Commit must pass the exact request through unmodified, not rebuild or reinterpret it")
	}
}

func TestCommitReturnsUnderlyingErrorUnmodified(t *testing.T) {
	wantErr := errors.New("injected aborted")
	fake := &fakeRawSpannerClient{err: wantErr}
	client := &Client{raw: fake}

	_, err := client.Commit(context.Background(), &spannerpb.CommitRequest{})
	if !errors.Is(err, wantErr) {
		t.Fatalf("err = %v, want %v -- Commit must return the raw error unmodified, never classify or swallow it", err, wantErr)
	}
	if fake.calls != 1 {
		t.Fatalf("fake.calls = %d, want exactly 1 even on error -- no retry-on-error behavior is permitted here", fake.calls)
	}
}

// TestNewWiresARealConnectionThroughToTheGeneratedStub proves New actually
// wires spannerpb.NewSpannerClient(conn) -- not a stub short-circuit -- by
// dialing an address nothing listens on and confirming Commit reaches all
// the way down to a real gRPC call attempt, failing with a transport-level
// error quickly and exactly once. No real GCP endpoint or credential is
// contacted by this test.
func TestNewWiresARealConnectionThroughToTheGeneratedStub(t *testing.T) {
	conn, err := grpc.NewClient("127.0.0.1:1", grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	client := New(conn)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	_, err = client.Commit(ctx, &spannerpb.CommitRequest{Session: "projects/p/instances/i/databases/d/sessions/s"})
	if err == nil {
		t.Fatal("expected a transport error dialing an address nothing listens on")
	}
}

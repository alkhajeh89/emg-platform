package spanneradapter

import (
	"context"
	"sync"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
)

// CommitAttempt records one Commit RPC actually sent over the wire, as
// observed by the caller -- not by the backend. It exists so emulator
// harness tests can assert on attempt counts (T12) without needing to
// parse emulator logs.
type CommitAttempt struct {
	Session       string
	TransactionID []byte
	Succeeded     bool
	Err           error
}

// InstrumentedCommitClient wraps a real spannerpb.SpannerClient and counts
// Commit calls without altering behavior: it performs no retry, no
// suppression, no injected delay. Its method signature is identical to
// rotationcommit.RawCommitClient's, so it can be passed directly into
// rotationcommit's unexported completeRawCommit from within that package's
// own test files.
type InstrumentedCommitClient struct {
	inner spannerpb.SpannerClient

	mu       sync.Mutex
	attempts []CommitAttempt
}

func NewInstrumentedCommitClient(inner spannerpb.SpannerClient) *InstrumentedCommitClient {
	return &InstrumentedCommitClient{inner: inner}
}

func (c *InstrumentedCommitClient) Commit(
	ctx context.Context,
	req *spannerpb.CommitRequest,
	opts ...grpc.CallOption,
) (*spannerpb.CommitResponse, error) {
	response, err := c.inner.Commit(ctx, req, opts...)
	c.mu.Lock()
	c.attempts = append(c.attempts, CommitAttempt{
		Session:       req.GetSession(),
		TransactionID: req.GetTransactionId(),
		Succeeded:     err == nil,
		Err:           err,
	})
	c.mu.Unlock()
	return response, err
}

// Attempts returns a snapshot of every Commit call observed so far.
func (c *InstrumentedCommitClient) Attempts() []CommitAttempt {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]CommitAttempt, len(c.attempts))
	copy(out, c.attempts)
	return out
}

func (c *InstrumentedCommitClient) AttemptCount() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return len(c.attempts)
}

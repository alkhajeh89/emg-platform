package rotationcommit

import (
	"context"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
)

// RawCommitClient is the only permitted future Commit boundary. Implementations
// must use the raw generated gRPC stub with configured retries disabled.
// Generated GAX clients, high-level transaction helpers, and multiplexed
// sessions are prohibited for this authority path.
type RawCommitClient interface {
	Commit(context.Context, *spannerpb.CommitRequest, ...grpc.CallOption) (*spannerpb.CommitResponse, error)
}

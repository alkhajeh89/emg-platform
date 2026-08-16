// Package spannercommit is the production, non-test Cloud Spanner Commit
// adapter authorized by ADR-045's Track B (S2). It implements only the
// minimal rotationcommit.RawCommitClient boundary -- a single raw Commit
// RPC, nothing more -- using the same raw generated spannerpb.SpannerClient
// stub that rotationcommit.RawCommitClient already requires.
//
// It deliberately does NOT provide session creation, transaction
// management, or any commit-outcome classification. Session/transaction
// orchestration belongs to a PREPARE/CAS harness layer above rotationcommit
// that has not been built yet (see conformance/spanneradapter's
// TransitionMutations doc comment), and outcome classification is
// rotationcommit's own frozen, already-qualified logic (ADR-043). This
// package's only job is to get a single Commit RPC to the real Cloud
// Spanner service and hand back its raw response or error, unmodified,
// exactly once -- so it never touches, and never needs to know, any
// instance/database resource path, staging or production alike.
//
// Forbidden by design, and never introduced here: cloud.google.com/go/spanner
// (the high-level client), ReadWriteTransaction, Apply, GAX retry helpers,
// multiplexed sessions, internal Commit retries, and any embedded
// credential or service-account key. Authentication is Application Default
// Credentials / workload-identity only, via google.golang.org/api/transport/grpc
// -- the same ADC resolution every Google Cloud client library uses,
// without pulling in a generated GAX service client for Spanner itself.
package spannercommit

import (
	"context"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/api/option"
	transportgrpc "google.golang.org/api/transport/grpc"
	"google.golang.org/grpc"
)

// defaultEndpoint is the single, universal Cloud Spanner API endpoint --
// the same fixed host every Cloud Spanner client library dials regardless
// of which project, instance, or environment it talks to. It is not a
// staging/production resource identifier.
const defaultEndpoint = "spanner.googleapis.com:443"

// spannerDataScope is the least-privilege OAuth scope this Commit-only
// boundary needs: it can read/write data but cannot create, delete, or
// reconfigure Spanner instances or databases.
const spannerDataScope = "https://www.googleapis.com/auth/spanner.data"

// Dial opens a real, authenticated gRPC connection to Cloud Spanner using
// Application Default Credentials -- whatever credential the caller's
// environment or workload-identity configuration resolves (metadata
// server, gcloud ADC file, GOOGLE_APPLICATION_CREDENTIALS, workload
// identity federation). This function never supplies a static, embedded,
// or service-account-key credential itself. Additional option.ClientOption
// values may be supplied by the caller (e.g. to point at a specific
// ADC-compatible credential source their deployment requires); this
// function never hardcodes one.
func Dial(ctx context.Context, opts ...option.ClientOption) (*grpc.ClientConn, error) {
	allOpts := append([]option.ClientOption{
		option.WithEndpoint(defaultEndpoint),
		option.WithScopes(spannerDataScope),
	}, opts...)
	return transportgrpc.Dial(ctx, allOpts...)
}

// Client implements rotationcommit.RawCommitClient by delegating directly
// to the raw generated spannerpb.SpannerClient stub: exactly one Commit RPC
// per Commit call, no retry, no classification, no reinterpretation of the
// response or error.
type Client struct {
	raw spannerpb.SpannerClient
}

// New wraps conn (as produced by Dial) as a Client. conn's lifecycle
// (Close) remains the caller's responsibility.
func New(conn *grpc.ClientConn) *Client {
	return &Client{raw: spannerpb.NewSpannerClient(conn)}
}

// Commit issues exactly one Commit RPC and returns its raw response or
// error unmodified. It never retries, never inspects the response beyond
// returning it, and never resolves ambiguity -- that is
// rotationcommit.ClassifyCommit's job, on the caller's side of this
// boundary.
func (c *Client) Commit(ctx context.Context, req *spannerpb.CommitRequest, opts ...grpc.CallOption) (*spannerpb.CommitResponse, error) {
	return c.raw.Commit(ctx, req, opts...)
}

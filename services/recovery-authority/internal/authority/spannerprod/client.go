// Package spannerprod provides the production transport boundary for the
// Recovery Authority's single raw Cloud Spanner Commit RPC.
//
// It deliberately owns no session, transaction, classification, readback,
// witness, signing, or recovery behavior. Callers supply a fully formed raw
// CommitRequest and remain responsible for interpreting the exact response and
// error returned by Cloud Spanner.
package spannerprod

import (
	"context"
	"crypto/tls"
	"errors"
	"fmt"
	"net"
	"strconv"
	"strings"
	"sync"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"golang.org/x/oauth2"
	"golang.org/x/oauth2/google"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/oauth"
)

const spannerDataScope = "https://www.googleapis.com/auth/spanner.data"

// Config contains the transport configuration needed by the raw Commit
// client. Endpoint must be an explicit host:port. Database and session names
// are intentionally absent: the raw CommitRequest carries its fully qualified
// session and this adapter does not own session or transaction orchestration.
type Config struct {
	Endpoint string
}

type rawCommitClient interface {
	Commit(context.Context, *spannerpb.CommitRequest, ...grpc.CallOption) (*spannerpb.CommitResponse, error)
}

// Client is a minimal, owned raw Commit transport. Its Commit method satisfies
// rotationcommit.RawCommitClient structurally without importing application
// or protocol packages into this provider adapter.
type Client struct {
	raw     rawCommitClient
	closeFn func() error

	closeOnce sync.Once
	closeErr  error
}

// New creates a TLS-authenticated raw Spanner client using Application Default
// Credentials. ADC keeps this constructor compatible with workload identity;
// no static token, service-account key, or credential-file option is exposed.
func New(ctx context.Context, cfg Config) (*Client, error) {
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}
	adc, err := google.FindDefaultCredentials(ctx, spannerDataScope)
	if err != nil {
		return nil, fmt.Errorf("spanner production credentials: %w", err)
	}
	return newAuthenticatedClient(cfg, adc.TokenSource)
}

func validateConfig(cfg Config) error {
	if cfg.Endpoint == "" {
		return errors.New("spanner production endpoint is required")
	}
	if strings.TrimSpace(cfg.Endpoint) != cfg.Endpoint {
		return errors.New("spanner production endpoint must not contain surrounding whitespace")
	}
	host, port, err := net.SplitHostPort(cfg.Endpoint)
	if err != nil || host == "" || port == "" {
		return fmt.Errorf("spanner production endpoint must be host:port: %q", cfg.Endpoint)
	}
	portNumber, err := strconv.ParseUint(port, 10, 16)
	if err != nil || portNumber == 0 {
		return fmt.Errorf("spanner production endpoint port is invalid: %q", cfg.Endpoint)
	}
	return nil
}

func newAuthenticatedClient(cfg Config, tokenSource oauth2.TokenSource) (*Client, error) {
	if err := validateConfig(cfg); err != nil {
		return nil, err
	}
	if tokenSource == nil {
		return nil, errors.New("spanner production token source is required")
	}
	transportCredentials := credentials.NewTLS(&tls.Config{MinVersion: tls.VersionTLS12})
	perRPCCredentials := oauth.TokenSource{TokenSource: tokenSource}
	return dial(cfg.Endpoint, transportCredentials, perRPCCredentials)
}

func dial(
	endpoint string,
	transportCredentials credentials.TransportCredentials,
	perRPCCredentials credentials.PerRPCCredentials,
) (*Client, error) {
	if transportCredentials == nil {
		return nil, errors.New("spanner production transport credentials are required")
	}
	opts := []grpc.DialOption{
		grpc.WithTransportCredentials(transportCredentials),
		// ADR-044 permits one application-level Commit attempt. Disable both
		// resolver-provided retry policies and gRPC configured retries. grpc-go
		// may still recreate a stream only before request bytes are written, or
		// when the server explicitly reports the stream unprocessed; neither is
		// a provider-processed Commit attempt and neither can conceal ambiguity.
		grpc.WithDisableServiceConfig(),
		grpc.WithDisableRetry(),
	}
	if perRPCCredentials != nil {
		opts = append(opts, grpc.WithPerRPCCredentials(perRPCCredentials))
	}
	conn, err := grpc.NewClient(endpoint, opts...)
	if err != nil {
		return nil, fmt.Errorf("create raw Spanner connection: %w", err)
	}
	return newClient(spannerpb.NewSpannerClient(conn), conn.Close)
}

func newClient(raw rawCommitClient, closeFn func() error) (*Client, error) {
	if raw == nil {
		return nil, errors.New("raw Spanner client is required")
	}
	if closeFn == nil {
		return nil, errors.New("raw Spanner transport close function is required")
	}
	return &Client{raw: raw, closeFn: closeFn}, nil
}

// Commit performs exactly one call through the raw generated Spanner stub. It
// does not retry, classify, read back state, or alter the request, response, or
// error. Caller call options are preserved in order; the mandatory no-replay
// option is appended last.
func (c *Client) Commit(
	ctx context.Context,
	req *spannerpb.CommitRequest,
	opts ...grpc.CallOption,
) (*spannerpb.CommitResponse, error) {
	// grpc-go's WithDisableRetry disables configured retry policies but, by
	// itself, still permits transparent replay while an RPC remains buffered.
	// A zero retry buffer commits the attempt as soon as the request payload is
	// prepared, preventing any replay after a Commit request can be sent. Put it
	// last so a caller cannot override this authority invariant.
	singleAttemptOpts := make([]grpc.CallOption, 0, len(opts)+1)
	singleAttemptOpts = append(singleAttemptOpts, opts...)
	singleAttemptOpts = append(singleAttemptOpts, grpc.MaxRetryRPCBufferSize(0))
	return c.raw.Commit(ctx, req, singleAttemptOpts...)
}

// Close closes the owned gRPC transport once and returns its exact close
// result on every call.
func (c *Client) Close() error {
	c.closeOnce.Do(func() { c.closeErr = c.closeFn() })
	return c.closeErr
}

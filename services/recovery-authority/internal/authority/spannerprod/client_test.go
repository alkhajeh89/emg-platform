package spannerprod

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit"
	"golang.org/x/oauth2"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/metadata"
	"google.golang.org/grpc/status"
)

var _ rotationcommit.RawCommitClient = (*Client)(nil)

type fakeRawCommitClient struct {
	calls    int
	request  *spannerpb.CommitRequest
	options  []grpc.CallOption
	response *spannerpb.CommitResponse
	err      error
}

func (f *fakeRawCommitClient) Commit(
	_ context.Context,
	req *spannerpb.CommitRequest,
	opts ...grpc.CallOption,
) (*spannerpb.CommitResponse, error) {
	f.calls++
	f.request = req
	f.options = append([]grpc.CallOption(nil), opts...)
	return f.response, f.err
}

func newTestClient(t *testing.T, raw rawCommitClient, closeFn func() error) *Client {
	t.Helper()
	client, err := newClient(raw, closeFn)
	if err != nil {
		t.Fatal(err)
	}
	return client
}

func TestCommitForwardsRequestOptionsAndResponseUnchanged(t *testing.T) {
	raw := &fakeRawCommitClient{response: &spannerpb.CommitResponse{}}
	client := newTestClient(t, raw, func() error { return nil })
	request := &spannerpb.CommitRequest{Session: "projects/p/instances/i/databases/d/sessions/s"}
	var header metadata.MD
	var trailer metadata.MD
	options := []grpc.CallOption{grpc.Header(&header), grpc.Trailer(&trailer)}

	response, err := client.Commit(context.Background(), request, options...)
	if err != nil {
		t.Fatal(err)
	}
	if raw.calls != 1 {
		t.Fatalf("Commit calls = %d, want 1", raw.calls)
	}
	if raw.request != request {
		t.Fatal("CommitRequest pointer was not forwarded unchanged")
	}
	if len(raw.options) != len(options)+1 {
		t.Fatalf("call options count = %d, want %d caller options plus one mandatory no-replay option", len(raw.options), len(options)+1)
	}
	if !reflect.DeepEqual(raw.options[:len(options)], options) {
		t.Fatalf("caller call options changed: got %#v, want %#v", raw.options[:len(options)], options)
	}
	noReplay, ok := raw.options[len(options)].(grpc.MaxRetryRPCBufferSizeCallOption)
	if !ok {
		t.Fatalf("last call option = %T, want mandatory MaxRetryRPCBufferSizeCallOption", raw.options[len(options)])
	}
	if noReplay.MaxRetryRPCBufferSize != 0 {
		t.Fatalf("retry RPC buffer size = %d, want 0", noReplay.MaxRetryRPCBufferSize)
	}
	if response != raw.response {
		t.Fatal("CommitResponse pointer was not returned unchanged")
	}
}

func TestCommitReturnsErrorsUnchangedWithoutRetry(t *testing.T) {
	transportErr := errors.New("synthetic transport failure")
	tests := []struct {
		name string
		err  error
	}{
		{name: "aborted", err: status.Error(codes.Aborted, "synthetic")},
		{name: "deadline_exceeded", err: status.Error(codes.DeadlineExceeded, "synthetic")},
		{name: "unavailable", err: status.Error(codes.Unavailable, "synthetic")},
		{name: "non_grpc", err: transportErr},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			raw := &fakeRawCommitClient{err: test.err}
			client := newTestClient(t, raw, func() error { return nil })
			response, err := client.Commit(context.Background(), &spannerpb.CommitRequest{})
			if response != nil {
				t.Fatalf("response = %#v, want nil", response)
			}
			if err != test.err {
				t.Fatalf("error changed: got %v, want exact %v", err, test.err)
			}
			if raw.calls != 1 {
				t.Fatalf("Commit calls = %d, want 1", raw.calls)
			}
		})
	}
}

func TestCommitDoesNotRepairNilOrMalformedResponse(t *testing.T) {
	tests := []struct {
		name     string
		response *spannerpb.CommitResponse
	}{
		{name: "nil", response: nil},
		{name: "missing_commit_timestamp", response: &spannerpb.CommitResponse{}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			raw := &fakeRawCommitClient{response: test.response}
			client := newTestClient(t, raw, func() error { return nil })
			response, err := client.Commit(context.Background(), nil)
			if err != nil {
				t.Fatal(err)
			}
			if response != test.response {
				t.Fatalf("response changed: got %#v, want %#v", response, test.response)
			}
			if raw.request != nil || raw.calls != 1 {
				t.Fatalf("nil request forwarding changed: request=%#v calls=%d", raw.request, raw.calls)
			}
		})
	}
}

func TestCloseClosesOwnedTransportExactlyOnce(t *testing.T) {
	wantErr := errors.New("synthetic close failure")
	closeCalls := 0
	client := newTestClient(t, &fakeRawCommitClient{}, func() error {
		closeCalls++
		return wantErr
	})
	for range 2 {
		if err := client.Close(); err != wantErr {
			t.Fatalf("Close error changed: got %v, want exact %v", err, wantErr)
		}
	}
	if closeCalls != 1 {
		t.Fatalf("transport close calls = %d, want 1", closeCalls)
	}
}

func TestConfigurationValidationFailsClosed(t *testing.T) {
	tests := []Config{
		{},
		{Endpoint: "spanner.googleapis.com"},
		{Endpoint: "https://spanner.googleapis.com:443"},
		{Endpoint: " spanner.googleapis.com:443"},
		{Endpoint: ":443"},
		{Endpoint: "spanner.googleapis.com:not-a-port"},
		{Endpoint: "spanner.googleapis.com:0"},
	}
	for _, cfg := range tests {
		if err := validateConfig(cfg); err == nil {
			t.Errorf("validateConfig(%q) succeeded, want error", cfg.Endpoint)
		}
	}
}

func TestAuthenticatedConstructorRequiresTokenSource(t *testing.T) {
	_, err := newAuthenticatedClient(Config{Endpoint: "spanner.googleapis.com:443"}, nil)
	if err == nil {
		t.Fatal("nil token source succeeded")
	}
}

type inertTokenSource struct{}

func (inertTokenSource) Token() (*oauth2.Token, error) {
	return nil, errors.New("must not be called while constructing a lazy gRPC connection")
}

func TestAuthenticatedConstructorBuildsAndClosesLazyConnection(t *testing.T) {
	client, err := newAuthenticatedClient(
		Config{Endpoint: "spanner.googleapis.com:443"},
		inertTokenSource{},
	)
	if err != nil {
		t.Fatal(err)
	}
	if err := client.Close(); err != nil {
		t.Fatal(err)
	}
}

func TestNewClientValidation(t *testing.T) {
	if _, err := newClient(nil, func() error { return nil }); err == nil {
		t.Fatal("nil raw client succeeded")
	}
	if _, err := newClient(&fakeRawCommitClient{}, nil); err == nil {
		t.Fatal("nil close function succeeded")
	}
}

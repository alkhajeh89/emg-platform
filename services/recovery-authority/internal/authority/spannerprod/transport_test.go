package spannerprod

import (
	"context"
	"net"
	"sync"
	"testing"

	"cloud.google.com/go/spanner/apiv1/spannerpb"
	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials/insecure"
	"google.golang.org/grpc/status"
)

type countingSpannerServer struct {
	spannerpb.UnimplementedSpannerServer

	mu       sync.Mutex
	calls    int
	response *spannerpb.CommitResponse
	err      error
}

func (s *countingSpannerServer) Commit(
	context.Context,
	*spannerpb.CommitRequest,
) (*spannerpb.CommitResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.calls++
	return s.response, s.err
}

func (s *countingSpannerServer) callCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.calls
}

func startTestServer(t *testing.T, service *countingSpannerServer) string {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	server := grpc.NewServer()
	spannerpb.RegisterSpannerServer(server, service)
	go func() {
		if serveErr := server.Serve(listener); serveErr != nil {
			return
		}
	}()
	t.Cleanup(func() {
		server.Stop()
		listener.Close()
	})
	return listener.Addr().String()
}

func TestConfiguredTransportDoesNotRetryProviderErrors(t *testing.T) {
	tests := []codes.Code{codes.Aborted, codes.DeadlineExceeded, codes.Unavailable}
	for _, code := range tests {
		t.Run(code.String(), func(t *testing.T) {
			service := &countingSpannerServer{err: status.Error(code, "synthetic")}
			endpoint := startTestServer(t, service)
			client, err := dial(endpoint, insecure.NewCredentials(), nil)
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { client.Close() })

			_, gotErr := client.Commit(context.Background(), &spannerpb.CommitRequest{})
			if status.Code(gotErr) != code {
				t.Fatalf("status code = %v, want %v", status.Code(gotErr), code)
			}
			if service.callCount() != 1 {
				t.Fatalf("provider Commit calls = %d, want 1", service.callCount())
			}
		})
	}
}

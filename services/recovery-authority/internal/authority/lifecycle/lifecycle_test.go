package lifecycle

import (
	"context"
	"net/http"
	"net/http/httptest"
	"syscall"
	"testing"
	"time"
)

func TestReadinessStartsFalse(t *testing.T) {
	r := &Readiness{}
	if r.IsReady() {
		t.Fatal("readiness must start false")
	}
}

func TestReadinessBecomesTrueOnlyAfterSetReady(t *testing.T) {
	r := &Readiness{}
	r.SetReady()
	if !r.IsReady() {
		t.Fatal("expected readiness true after SetReady")
	}
	r.SetNotReady()
	if r.IsReady() {
		t.Fatal("expected readiness false after SetNotReady")
	}
}

func TestHealthzAlwaysReportsOKRegardlessOfReadiness(t *testing.T) {
	r := &Readiness{}
	server := httptest.NewServer(Handler(r))
	defer server.Close()

	resp, err := http.Get(server.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		t.Fatalf("healthz before ready: status = %d, want 200", resp.StatusCode)
	}

	r.SetReady()
	resp2, err := http.Get(server.URL + "/healthz")
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != http.StatusOK {
		t.Fatalf("healthz after ready: status = %d, want 200", resp2.StatusCode)
	}
}

// TestReadyzFalseBeforeInitializationTrueAfter is the direct S5 Phase 7
// item 12 regression test.
func TestReadyzFalseBeforeInitializationTrueAfter(t *testing.T) {
	r := &Readiness{}
	server := httptest.NewServer(Handler(r))
	defer server.Close()

	resp, err := http.Get(server.URL + "/readyz")
	if err != nil {
		t.Fatal(err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusServiceUnavailable {
		t.Fatalf("readyz before init: status = %d, want 503", resp.StatusCode)
	}

	r.SetReady()
	resp2, err := http.Get(server.URL + "/readyz")
	if err != nil {
		t.Fatal(err)
	}
	defer resp2.Body.Close()
	if resp2.StatusCode != http.StatusOK {
		t.Fatalf("readyz after init: status = %d, want 200", resp2.StatusCode)
	}
}

// TestRunGracefulShutdownOnSignal is the direct S5 Phase 7 item 11 /
// Phase 8 Attack K regression test: sends SIGTERM to this test process
// and confirms Run returns cleanly within the shutdown deadline.
func TestRunGracefulShutdownOnSignal(t *testing.T) {
	r := &Readiness{}
	r.SetReady()
	logger := NewLogger()

	done := make(chan error, 1)
	go func() {
		done <- Run(context.Background(), logger, "127.0.0.1:0", Handler(r), 2*time.Second)
	}()

	// Give the server a moment to start listening, then simulate an
	// operator/orchestrator-issued SIGTERM.
	time.Sleep(50 * time.Millisecond)
	if err := syscall.Kill(syscall.Getpid(), syscall.SIGTERM); err != nil {
		t.Fatal(err)
	}

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run returned an error on graceful shutdown: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return within the bounded shutdown window")
	}
}

func TestRunReturnsErrorOnListenFailure(t *testing.T) {
	r := &Readiness{}
	// Bind a listener first so the second bind on the same address fails
	// deterministically.
	blocking := httptest.NewServer(Handler(r))
	defer blocking.Close()

	logger := NewLogger()
	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	err := Run(ctx, logger, blocking.Listener.Addr().String(), Handler(r), time.Second)
	if err == nil {
		t.Fatal("expected Run to return an error when the listen address is already in use")
	}
}

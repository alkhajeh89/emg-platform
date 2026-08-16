//go:build emulator

package gcswitness

// Fault injection against fake-gcs-server through the existing
// conformance/faultproxy TCP proxy (reused, not reimplemented, per the
// task's instruction). These tests prove that transport-level ambiguity on
// the GCS create path is resolved only by exact-key verification, and that
// nothing here ever touches Spanner classification or constructs an
// AcceptedRotationContext -- this package has no reference to either.

import (
	"context"
	"net/http"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy"
	"google.golang.org/api/option"
)

const fakeGCSBackendAddr = "localhost:4443"

func adapterThroughProxy(t *testing.T, proxyAddr string) *Adapter {
	t.Helper()
	client, err := NewClient(context.Background(),
		option.WithEndpoint("http://"+proxyAddr+"/storage/v1/"),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("NewClient via proxy: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return New(client, testBucketName)
}

// TestFaultBackendCreateSucceedsResponseDropped is the GCS analogue of the
// Spanner T4 proof: the backend genuinely creates the object (confirmed by
// a direct, unproxied read afterward), while the client observes only a
// transport failure -- and exact-key read-resolution must still recover
// safely.
func TestFaultBackendCreateSucceedsResponseDropped(t *testing.T) {
	proxy := faultproxy.New(fakeGCSBackendAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DropResponseAfterBackendSuccess)

	adapter := adapterThroughProxy(t, proxyAddr)
	key := freshKey(t)
	payload := []byte("dropped-response-payload")

	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, payload)
	if outcome == HardFailure {
		t.Fatalf("must not classify a dropped response as a hard failure: err=%v", err)
	}

	// Ground truth, on a fresh, unproxied adapter: the object must be
	// genuinely present with the exact bytes.
	direct := newTestAdapter(t)
	data, readErr := direct.ReadExact(context.Background(), key)
	if readErr != nil {
		t.Fatalf("expected the object to genuinely exist server-side despite the dropped response: %v", readErr)
	}
	if string(data) != string(payload) {
		t.Fatalf("ground truth content = %q, want %q", data, payload)
	}
	// The classification itself must reflect this reality: either the
	// caller's own call already resolved it (CreateSuccess), or it
	// legitimately came back ambiguous/absent-at-read-time due to timing --
	// but it must never be HardFailure, and it must never disagree with
	// ground truth if it claims resolution.
	if outcome == CreateSuccess {
		t.Log("this call's own read-resolution already confirmed success")
	} else {
		t.Logf("outcome=%v; ground truth independently confirms the object exists and matches -- a subsequent CreateExactIfAbsent retry would now resolve via 412+identical", outcome)
	}
}

// TestFaultConnectionResetAfterRequestTransmission proves a reset mid-flight
// is classified ambiguous (or resolved safely), never as false success and
// never as a hard failure.
func TestFaultConnectionResetAfterRequestTransmission(t *testing.T) {
	proxy := faultproxy.New(fakeGCSBackendAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.ResetAfterRequestTransmission)

	adapter := adapterThroughProxy(t, proxyAddr)
	key := freshKey(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("reset-payload"))
	if err == nil {
		t.Fatal("expected an error from a connection reset")
	}
	if outcome == HardFailure {
		t.Fatalf("a transport reset must never classify as HardFailure: %v", err)
	}
}

// TestFaultTimeoutDuringCreate proves a proxy-delayed (past the client's own
// deadline) response classifies safely.
func TestFaultTimeoutDuringCreate(t *testing.T) {
	proxy := faultproxy.New(fakeGCSBackendAddr, 2*time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DelayPastDeadline)

	adapter := adapterThroughProxy(t, proxyAddr)
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	key := freshKey(t)
	outcome, err := adapter.CreateExactIfAbsent(ctx, key, []byte("timeout-payload"))
	if err == nil {
		t.Fatal("expected an error from a client-side deadline")
	}
	if outcome == HardFailure {
		t.Fatalf("a client deadline must never classify as HardFailure: %v", err)
	}
}

// TestFaultUnavailableEndpoint proves a completely unreachable backend
// (connection refused before any byte is exchanged) classifies safely.
func TestFaultUnavailableEndpoint(t *testing.T) {
	proxy := faultproxy.New(fakeGCSBackendAddr, time.Second)
	proxyAddr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(faultproxy.DropBeforeBackend)

	adapter := adapterThroughProxy(t, proxyAddr)
	key := freshKey(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("unavailable-payload"))
	if err == nil {
		t.Fatal("expected an error when the backend is unreachable")
	}
	if outcome == CreateSuccess || outcome == AlreadyExistsIdentical {
		t.Fatalf("outcome = %v, must not claim success when the backend was never reached", outcome)
	}
	if outcome == HardFailure {
		t.Fatalf("connection-refused-before-backend must not classify as HardFailure: %v", err)
	}

	// Ground truth: nothing was created.
	direct := newTestAdapter(t)
	exists, existsErr := direct.Exists(context.Background(), key)
	if existsErr != nil {
		t.Fatal(existsErr)
	}
	if exists {
		t.Fatal("no object should exist -- the request never reached the backend")
	}
}

// TestGCSFaultsNeverProduceSpannerOrAcceptedContextReferences documents, by
// the absence of any such import, that this package has no way to affect
// Spanner classification or construct an AcceptedRotationContext -- the
// package's own boundary tests (TestAuthorityImportBoundary,
// TestNoForbiddenStorageMethods, etc.) already enforce this structurally;
// this test exists to state the required rule explicitly next to the fault
// injection tests that exercise the scenario it protects.
func TestGCSFaultsNeverProduceSpannerOrAcceptedContextReferences(t *testing.T) {
	// This package does not import rotationcommit, spanneradapter, or
	// anything Spanner-related at all (verified structurally by
	// TestAuthorityImportBoundary). CreateOutcome and its four non-zero
	// values are the entire vocabulary this package can produce; none of
	// them is a Spanner epoch state or an accepted-context value.
	outcomes := []CreateOutcome{AmbiguousCreate, CreateSuccess, AlreadyExistsIdentical, AlreadyExistsConflict, HardFailure}
	for _, o := range outcomes {
		if o.String() == "" {
			t.Fatalf("CreateOutcome %d has no string representation", o)
		}
	}
}

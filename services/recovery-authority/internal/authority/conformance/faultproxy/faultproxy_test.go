//go:build emulator

package faultproxy

import (
	"context"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter"
)

const emulatorAddr = "localhost:9010"
const emulatorDatabase = "projects/emg-recovery-authority-test/instances/test-instance/databases/test-db"

func newSessionThroughProxy(t *testing.T, addr string) (*spanneradapter.Client, string) {
	t.Helper()
	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatalf("dial proxy: %v", err)
	}
	t.Cleanup(func() { conn.Close() })
	client := spanneradapter.New(conn, emulatorDatabase)
	session, err := client.CreateSession(context.Background())
	if err != nil {
		t.Fatalf("CreateSession through proxy: %v", err)
	}
	return client, session
}

// waitForRecords polls Records() until exactly want records are present,
// or fails the test. Needed because record delivery/byte-count fields are
// updated live by background goroutines, not synchronously with the
// client-visible RPC error.
func waitForRecords(t *testing.T, proxy *Proxy, want int) []ConnectionRecord {
	t.Helper()
	deadline := time.Now().Add(2 * time.Second)
	var records []ConnectionRecord
	for time.Now().Before(deadline) {
		records = proxy.Records()
		if len(records) == want {
			return records
		}
		time.Sleep(10 * time.Millisecond)
	}
	t.Fatalf("len(records) = %d, want %d", len(records), want)
	return nil
}

// TestPassThroughRelaysRealTraffic proves the proxy is transparent when no
// fault is queued: a real CreateSession round-trip through the proxy
// behaves identically to dialing the emulator directly.
func TestPassThroughRelaysRealTraffic(t *testing.T) {
	proxy := New(emulatorAddr, time.Second)
	addr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()

	_, session := newSessionThroughProxy(t, addr)
	if session == "" {
		t.Fatal("expected a non-empty session name")
	}
	records := waitForRecords(t, proxy, 1)
	if !records[0].ResponseDeliveredToClient {
		t.Fatal("expected the pass-through connection to deliver a response")
	}
}

// TestDropBeforeBackendNeverDialsBackend proves fault B: the proxy refuses
// the connection before the backend is ever contacted.
func TestDropBeforeBackendNeverDialsBackend(t *testing.T) {
	proxy := New(emulatorAddr, time.Second)
	addr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(DropBeforeBackend)

	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	client := spanneradapter.New(conn, emulatorDatabase)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	_, err = client.CreateSession(ctx)
	if err == nil {
		t.Fatal("expected CreateSession to fail when the connection is dropped before the backend")
	}

	records := proxy.Records()
	if len(records) != 1 {
		t.Fatalf("len(records) = %d, want 1", len(records))
	}
	if records[0].DialedBackend {
		t.Fatal("DropBeforeBackend must never dial the backend")
	}
}

// TestOneShotFaultAffectsOnlyOneConnection proves fault G: a queued fault
// applies to exactly one connection, and every subsequent connection is
// unaffected.
func TestOneShotFaultAffectsOnlyOneConnection(t *testing.T) {
	proxy := New(emulatorAddr, time.Second)
	addr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(DropBeforeBackend)

	failingConn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	failingClient := spanneradapter.New(failingConn, emulatorDatabase)
	ctx1, cancel1 := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel1()
	if _, err := failingClient.CreateSession(ctx1); err == nil {
		t.Fatal("expected the first (faulted) connection to fail")
	}
	failingConn.Close()

	_, session := newSessionThroughProxy(t, addr)
	if session == "" {
		t.Fatal("expected the second connection to succeed normally after the one-shot fault was consumed")
	}
}

// TestResetAfterRequestTransmissionRelaysRequestThenResets proves fault E:
// the request reaches the backend, but the connection is reset before any
// response is relayed.
func TestResetAfterRequestTransmissionRelaysRequestThenResets(t *testing.T) {
	proxy := New(emulatorAddr, time.Second)
	addr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(ResetAfterRequestTransmission)

	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	client := spanneradapter.New(conn, emulatorDatabase)
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	if _, err := client.CreateSession(ctx); err == nil {
		t.Fatal("expected CreateSession to fail when reset after transmission")
	}

	records := waitForRecords(t, proxy, 1)
	if !records[0].DialedBackend {
		t.Fatal("ResetAfterRequestTransmission must dial the backend")
	}
	if records[0].BytesRelayedToBackend == 0 {
		t.Fatal("expected some request bytes to have reached the backend before the reset")
	}
	if records[0].ResponseDeliveredToClient {
		t.Fatal("no response should have been delivered to the client")
	}
}

// TestDelayPastDeadlineExceedsClientDeadline proves fault D: the client's
// own context deadline elapses before the (deliberately delayed) response
// is relayed.
func TestDelayPastDeadlineExceedsClientDeadline(t *testing.T) {
	proxy := New(emulatorAddr, 2*time.Second)
	addr, err := proxy.Start()
	if err != nil {
		t.Fatal(err)
	}
	defer proxy.Close()
	proxy.QueueFault(DelayPastDeadline)

	conn, err := spanneradapter.Dial(context.Background(), addr)
	if err != nil {
		t.Fatal(err)
	}
	defer conn.Close()
	client := spanneradapter.New(conn, emulatorDatabase)
	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	start := time.Now()
	_, err = client.CreateSession(ctx)
	elapsed := time.Since(start)
	if err == nil {
		t.Fatal("expected CreateSession to fail due to the client deadline")
	}
	if elapsed > time.Second {
		t.Fatalf("elapsed = %v, want the client to give up near its own 200ms deadline, not wait for the proxy's delay", elapsed)
	}
}

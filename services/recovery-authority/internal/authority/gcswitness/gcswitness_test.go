//go:build emulator

package gcswitness

// Unit tests against fsouza/fake-gcs-server, a widely-used community GCS
// emulator (docker image pinned in the final report). Per the task
// authorization: this emulator is treated as NON-authoritative for any
// security-critical behavior (in particular Bucket Lock/retention, which is
// never exercised here) -- it is used only to exercise real HTTP request
// construction, real ifGenerationMatch/412 behavior, the real multipart
// upload path, and real exact-key GETs. Where its fidelity is uncertain,
// that is called out explicitly rather than assumed.

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"net/http"
	"testing"
	"time"

	"cloud.google.com/go/storage"
	"google.golang.org/api/googleapi"
	"google.golang.org/api/option"
)

const (
	fakeGCSEndpoint = "http://localhost:4443/storage/v1/"
	testBucketName  = "adr043-witness-test"
)

func newTestAdapter(t *testing.T) *Adapter {
	t.Helper()
	ctx := context.Background()
	client, err := NewClient(ctx,
		option.WithEndpoint(fakeGCSEndpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return New(client, testBucketName)
}

func freshKey(t *testing.T) string {
	t.Helper()
	suffix := make([]byte, 8)
	if _, err := rand.Read(suffix); err != nil {
		t.Fatal(err)
	}
	return "witness/" + t.Name() + "-" + hex.EncodeToString(suffix)
}

func TestCreateSuccess(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("payload-a"))
	if err != nil {
		t.Fatal(err)
	}
	if outcome != CreateSuccess {
		t.Fatalf("outcome = %v, want CreateSuccess", outcome)
	}
}

func TestExactDuplicateIsIdempotentIdentical(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	payload := []byte("payload-b")
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, payload); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, payload)
	if err != nil {
		t.Fatalf("retry with identical bytes must not return an error: %v", err)
	}
	if outcome != AlreadyExistsIdentical {
		t.Fatalf("outcome = %v, want AlreadyExistsIdentical", outcome)
	}
}

func TestSameKeyConflictingBytesFailsClosed(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("original")); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("different"))
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("err = %v, want ErrConflict", err)
	}
	if outcome != AlreadyExistsConflict {
		t.Fatalf("outcome = %v, want AlreadyExistsConflict", outcome)
	}
	// The original object must be completely unaffected -- no overwrite.
	data, readErr := adapter.ReadExact(context.Background(), key)
	if readErr != nil {
		t.Fatal(readErr)
	}
	if string(data) != "original" {
		t.Fatalf("stored content = %q, want unchanged %q", data, "original")
	}
}

func TestReadOfAbsentObjectFails(t *testing.T) {
	adapter := newTestAdapter(t)
	_, err := adapter.ReadExact(context.Background(), freshKey(t))
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("err = %v, want ErrNotFound", err)
	}
}

func TestExactReadSuccess(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	payload := []byte("exact-read-payload")
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, payload); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	data, err := adapter.ReadExact(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(data, payload) {
		t.Fatalf("data = %q, want %q", data, payload)
	}
}

// TestReadCorruptionOrErrorFailsClosed models a corrupted/truncated read by
// pointing the reader at a payload larger than the adapter's configured
// ceiling and confirming it is rejected rather than partially returned.
func TestReadCorruptionOrErrorFailsClosed(t *testing.T) {
	adapter := newTestAdapter(t)
	adapter.maxPayloadBytes = 8 // artificially tiny ceiling for this test
	key := freshKey(t)

	// Bypass the adapter's own size guard to create an oversized object
	// directly, simulating an object that is corrupt/unexpected relative to
	// this adapter's configured ceiling.
	full := New(mustDirectClient(t), testBucketName)
	if outcome, err := full.CreateExactIfAbsent(context.Background(), key, []byte("this-is-longer-than-eight-bytes")); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}

	_, err := adapter.ReadExact(context.Background(), key)
	if !errors.Is(err, ErrPayloadTooLarge) {
		t.Fatalf("err = %v, want ErrPayloadTooLarge", err)
	}
}

func mustDirectClient(t *testing.T) *storage.Client {
	t.Helper()
	client, err := NewClient(context.Background(),
		option.WithEndpoint(fakeGCSEndpoint),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close() })
	return client
}

func TestDeadlineExceededDuringCreateIsAmbiguousOrResolves(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	ctx, cancel := context.WithTimeout(context.Background(), 1*time.Nanosecond)
	defer cancel()
	time.Sleep(time.Millisecond) // ensure the deadline has genuinely passed
	outcome, err := adapter.CreateExactIfAbsent(ctx, key, []byte("payload"))
	if err == nil {
		t.Fatal("expected an error from an already-expired context")
	}
	if outcome != AmbiguousCreate && outcome != HardFailure {
		t.Fatalf("outcome = %v, want AmbiguousCreate or HardFailure for a context deadline failure", outcome)
	}
	// Whatever the classification, the object must not have been created
	// under conditions the caller cannot verify -- confirm via a fresh,
	// unexpired read.
	data, readErr := adapter.ReadExact(context.Background(), key)
	if errors.Is(readErr, ErrNotFound) {
		return // legitimately never reached the backend -- acceptable
	}
	if readErr != nil {
		t.Fatal(readErr)
	}
	if string(data) != "payload" {
		t.Fatalf("if the object exists at all, it must be exactly what was attempted; got %q", data)
	}
}

// TestAmbiguousCreateThenLaterIdenticalObjectResolvesSafely simulates T4-style
// ambiguity directly at the outcome-classification level: an error that is
// not a 412 and not a hard failure, followed by a read that finds identical
// bytes, must resolve to CreateSuccess (per the qualification's
// AMBIGUOUS_WRITE_ANALYSIS), never to AlreadyExistsIdentical (that outcome
// is reserved for a genuine 412).
func TestAmbiguousCreateThenLaterIdenticalObjectResolvesSafely(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	payload := []byte("resolved-by-read")

	// Simulate "the create actually landed server-side, but the client
	// observed a transient, non-412, non-hard-failure error" by creating
	// the object out-of-band first, then directly exercising the
	// classification helper with a synthetic ambiguous error.
	direct := New(mustDirectClient(t), testBucketName)
	if outcome, err := direct.CreateExactIfAbsent(context.Background(), key, payload); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}

	simulatedTransportErr := fmt.Errorf("simulated: %w", context.DeadlineExceeded)
	outcome, err := adapter.classifyCreateError(context.Background(), key, payload, simulatedTransportErr)
	if err != nil {
		t.Fatalf("expected safe resolution with no error, got: %v", err)
	}
	if outcome != CreateSuccess {
		t.Fatalf("outcome = %v, want CreateSuccess (ambiguous-but-resolved-identical)", outcome)
	}
}

// TestAmbiguousCreateThenLaterConflictingObjectFailsClosed is the same
// shape but with conflicting bytes at the key.
func TestAmbiguousCreateThenLaterConflictingObjectFailsClosed(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	direct := New(mustDirectClient(t), testBucketName)
	if outcome, err := direct.CreateExactIfAbsent(context.Background(), key, []byte("actual-content")); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}

	simulatedTransportErr := fmt.Errorf("simulated: %w", context.DeadlineExceeded)
	outcome, err := adapter.classifyCreateError(context.Background(), key, []byte("different-attempted-content"), simulatedTransportErr)
	if !errors.Is(err, ErrConflict) {
		t.Fatalf("err = %v, want ErrConflict", err)
	}
	if outcome != AlreadyExistsConflict {
		t.Fatalf("outcome = %v, want AlreadyExistsConflict", outcome)
	}
}

// TestAmbiguousCreateThenStillAbsentRemainsAmbiguous proves absence is
// never silently treated as proof the original create never reached GCS.
func TestAmbiguousCreateThenStillAbsentRemainsAmbiguous(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t) // deliberately never created

	simulatedTransportErr := fmt.Errorf("simulated: %w", context.DeadlineExceeded)
	outcome, err := adapter.classifyCreateError(context.Background(), key, []byte("attempted"), simulatedTransportErr)
	if outcome != AmbiguousCreate {
		t.Fatalf("outcome = %v, want AmbiguousCreate", outcome)
	}
	if err == nil {
		t.Fatal("expected a non-nil error for a still-ambiguous outcome")
	}
}

func TestNoOverwritePath(t *testing.T) {
	// Structural: CreateExactIfAbsent has no parameter or code path that
	// permits overwriting. This test documents and enforces that a
	// conflicting create at an existing key never modifies the existing
	// object, exercised twice to rule out any hidden second-attempt state.
	adapter := newTestAdapter(t)
	key := freshKey(t)
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("v1")); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	for i := 0; i < 3; i++ {
		adapter.CreateExactIfAbsent(context.Background(), key, []byte("attempted-overwrite"))
		data, err := adapter.ReadExact(context.Background(), key)
		if err != nil {
			t.Fatal(err)
		}
		if string(data) != "v1" {
			t.Fatalf("attempt %d: content changed to %q -- overwrite occurred", i, data)
		}
	}
}

func TestNoAlternateKeyFallback(t *testing.T) {
	// Structural: CreateExactIfAbsent's signature takes exactly one key and
	// never derives or tries a second one internally on conflict. This test
	// confirms no object appears at any deterministically-related alternate
	// key after a conflict.
	adapter := newTestAdapter(t)
	key := freshKey(t)
	adapter.CreateExactIfAbsent(context.Background(), key, []byte("v1"))
	adapter.CreateExactIfAbsent(context.Background(), key, []byte("v2-conflict"))
	for _, alt := range []string{key + "-1", key + "-2", key + "-retry", key + ".alt"} {
		exists, err := adapter.Exists(context.Background(), alt)
		if err != nil {
			t.Fatal(err)
		}
		if exists {
			t.Fatalf("unexpected object at alternate key %q", alt)
		}
	}
}

func TestLargePayloadRejectedOnCreate(t *testing.T) {
	adapter := newTestAdapter(t)
	oversized := make([]byte, MaxPayloadBytes+1)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), freshKey(t), oversized)
	if !errors.Is(err, ErrPayloadTooLarge) {
		t.Fatalf("err = %v, want ErrPayloadTooLarge", err)
	}
	if outcome != HardFailure {
		t.Fatalf("outcome = %v, want HardFailure", outcome)
	}
}

func TestEmptyPayloadRejected(t *testing.T) {
	adapter := newTestAdapter(t)
	outcome, err := adapter.CreateExactIfAbsent(context.Background(), freshKey(t), nil)
	if !errors.Is(err, ErrEmptyPayload) {
		t.Fatalf("err = %v, want ErrEmptyPayload", err)
	}
	if outcome != HardFailure {
		t.Fatalf("outcome = %v, want HardFailure", outcome)
	}
}

// TestDefensiveByteCopying proves the caller mutating its own slice after
// calling CreateExactIfAbsent cannot affect what was persisted.
func TestDefensiveByteCopying(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	payload := []byte("defensive-copy-payload")
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, payload); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	for i := range payload {
		payload[i] = 'X'
	}
	data, err := adapter.ReadExact(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if string(data) != "defensive-copy-payload" {
		t.Fatalf("stored content = %q, was affected by caller-side mutation", data)
	}
}

func TestExistsReflectsPresenceOnly(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	exists, err := adapter.Exists(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if exists {
		t.Fatal("expected not-exists before create")
	}
	if outcome, err := adapter.CreateExactIfAbsent(context.Background(), key, []byte("x")); err != nil || outcome != CreateSuccess {
		t.Fatalf("setup: outcome=%v err=%v", outcome, err)
	}
	exists, err = adapter.Exists(context.Background(), key)
	if err != nil {
		t.Fatal(err)
	}
	if !exists {
		t.Fatal("expected exists after create")
	}
}

// TestHardFailureIsNotResolvedByRead proves a definitive (in this
// simulation: a bad-request-shaped) failure is never routed through
// read-resolution -- it is classified as HardFailure directly, exactly the
// same way an ADR-043 Spanner ABORTED/hard-classified outcome is never
// re-litigated by a later read.
func TestHardFailureIsNotResolvedByRead(t *testing.T) {
	adapter := newTestAdapter(t)
	key := freshKey(t)
	simulatedHardErr := &googleapi.Error{Code: 403, Message: "simulated forbidden"}
	outcome, err := adapter.classifyCreateError(context.Background(), key, []byte("x"), simulatedHardErr)
	if outcome != HardFailure {
		t.Fatalf("outcome = %v, want HardFailure", outcome)
	}
	if err == nil {
		t.Fatal("expected a non-nil error")
	}
}

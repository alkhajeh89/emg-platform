//go:build emulator

package compromiseledger

// Caller-level regression coverage for the P0 GCS bucket-vs-object-404
// collapse (Wave 2 Track C): proves the fix in gcswitness.Adapter
// (confirmBucketExists, wired into Exists/ReadExact) propagates correctly
// through GCSLedger against a REAL gcswitness.Adapter backed by
// fake-gcs-server -- not a hand-written fake witness, which would trivially
// pass regardless of whether the underlying provider integration is
// correct.

import (
	"context"
	"net/http"
	"testing"
	"time"

	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
)

const nonexistentLedgerBucket = "compromiseledger-nonexistent-bucket-never-created"

func realGCSWitness(t *testing.T, bucket string) gcswitness.ImmutableWitness {
	t.Helper()
	client, err := gcswitness.NewClient(context.Background(),
		option.WithEndpoint("http://localhost:4443/storage/v1/"),
		option.WithoutAuthentication(),
		option.WithHTTPClient(&http.Client{}),
	)
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, bucket)
}

// Item 1 (positive control): existing bucket + no distrust record ->
// StatusNotDistrusted, nil -- against the REAL Adapter/emulator, not the
// in-memory fakeWitness this package's other tests use.
func TestRealAdapterStatusNotDistrustedWhenBucketExistsButRecordDoesNot(t *testing.T) {
	ledger, err := NewGCSLedger(realGCSWitness(t, "adr043-witness-test")) // pre-existing emulator bucket
	if err != nil {
		t.Fatal(err)
	}
	status, err := ledger.Status(context.Background(), "subject-never-declared-"+t.Name(), time.Now())
	if err != nil {
		t.Fatalf("Status against an existing bucket with no record must not error, got: %v", err)
	}
	if status != StatusNotDistrusted {
		t.Fatalf("status = %v, want StatusNotDistrusted", status)
	}
}

// Item 2/3: a nonexistent/unavailable ledger bucket must produce a non-nil
// error from Status -- never StatusNotDistrusted, nil. This is the direct
// regression test for the P0 finding: before the gcswitness fix, this
// returned (StatusNotDistrusted, nil), which is exactly the fail-open
// condition ADR-045 §7 forbids ("Unavailability of the compromise record
// ... SHALL fail closed").
func TestRealAdapterStatusFailsClosedWhenBucketMissing(t *testing.T) {
	ledger, err := NewGCSLedger(realGCSWitness(t, nonexistentLedgerBucket))
	if err != nil {
		t.Fatal(err)
	}
	status, err := ledger.Status(context.Background(), "any-subject", time.Now())
	if err == nil {
		t.Fatalf("expected a non-nil error when the ledger's bucket does not exist, got status=%v err=nil -- this is the exact P0 fail-open condition", status)
	}
	t.Logf("EVIDENCE: GCSLedger.Status against a nonexistent bucket correctly failed closed: %v", err)
}

// Item 4: the fail-closed error from Status must make it impossible for a
// caller (e.g. kmsverifier) to silently continue as if verification
// succeeded -- Status's own contract (Status, error) already makes this a
// caller-discipline requirement (the caller MUST check err), which
// kmsverifier.VerifyCommittedSignature already does (see
// realcloud_ledger_verifier_integration_test.go and kmsverifier/verifier.go:
// `if err != nil { return fmt.Errorf(...) }` immediately after the Status
// call, before ever reaching cryptographic verification). Re-verified here
// structurally: Status's error is non-nil in the missing-bucket case
// (proven above), and kmsverifier never inspects the Status value without
// first checking its error (unmodified by this task; see kmsverifier's own
// boundary_test.go).
func TestRealAdapterMissingBucketErrorIsNeverNil(t *testing.T) {
	ledger, err := NewGCSLedger(realGCSWitness(t, nonexistentLedgerBucket))
	if err != nil {
		t.Fatal(err)
	}
	_, statusErr := ledger.Status(context.Background(), "any-subject", time.Now())
	if statusErr == nil {
		t.Fatal("a nil error here would let a caller that (incorrectly) trusts the Status value alone silently proceed as verification-safe")
	}
}

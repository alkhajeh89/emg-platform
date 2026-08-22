//go:build realcloud_ledger

// Real-cloud compromise-ledger qualification (ADR-045 §7 Wave 2 Track C,
// Phase 8). Gated behind the realcloud_ledger build tag so it never runs as
// part of `go test ./...`, CI, or any other normal invocation -- it writes
// real objects to a real, disposable GCS bucket in a THIRD disposable
// project (emg-ra-ledger-qual-*), administratively distinct from both the
// authority/witness project (emg-adr043-disposable-witness, Wave 1) and the
// signing project (emg-ra-signing-qual-*, Phases 2-6), matching ADR-045 §7
// property 2's requirement that the compromise ledger be independent of
// both other domains. This is disposable mechanism qualification only; it
// does not itself prove administrative independence in the ADR-045 §15A
// sense (that requires genuinely separate Cloud Identity/Workspace
// administration, not three disposable projects under one organization).
//
// This file covers items 1-4 and 7-9 against the ledger alone. Items 10-11
// (the full sign/pin/ledger/verify pipeline) live in
// realcloud_ledger_verifier_integration_test.go as an EXTERNAL test package
// (compromiseledger_test) specifically to avoid an import cycle: kmsverifier
// imports compromiseledger, so a test needing both must not live in the
// internal compromiseledger package itself.
package compromiseledger

import (
	"context"
	"errors"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"golang.org/x/oauth2"
	"google.golang.org/api/option"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
)

func realCloudLedgerToken(t *testing.T) string {
	t.Helper()
	out, err := exec.Command("gcloud", "auth", "print-access-token").Output()
	if err != nil {
		t.Fatalf("gcloud auth print-access-token: %v", err)
	}
	token := strings.TrimSpace(string(out))
	if token == "" {
		t.Fatal("gcloud auth print-access-token returned an empty token")
	}
	return token
}

func realCloudLedgerBucket(t *testing.T) string {
	t.Helper()
	bucket := os.Getenv("EMG_REALCLOUD_LEDGER_BUCKET")
	if bucket == "" {
		t.Skip("EMG_REALCLOUD_LEDGER_BUCKET not set -- skipping real-cloud compromise-ledger qualification")
	}
	return bucket
}

func realLedgerWitness(t *testing.T, bucket string) gcswitness.ImmutableWitness {
	t.Helper()
	token := realCloudLedgerToken(t)
	client, err := gcswitness.NewClient(context.Background(), option.WithTokenSource(oauth2.StaticTokenSource(&oauth2.Token{AccessToken: token})))
	if err != nil {
		t.Fatalf("gcswitness.NewClient: %v", err)
	}
	t.Cleanup(func() { client.Close() })
	return gcswitness.New(client, bucket)
}

// TestRealCloudCompromiseLedgerQualification exercises items 1-4, 7-9
// against the real, unmodified production GCSLedger.
func TestRealCloudCompromiseLedgerQualification(t *testing.T) {
	bucket := realCloudLedgerBucket(t)
	witness := realLedgerWitness(t, bucket)
	ledger, err := NewGCSLedger(witness)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	now := time.Now().UTC()
	subject := "realcloud-ledger-qual-subject-" + now.Format("20060102T150405.000000000")

	record := DistrustRecord{
		Subject:       subject,
		EffectiveTime: now,
		RecordedAt:    now,
		Reason:        "realcloud-ledger-qualification",
		RecordedBy:    "realcloud-qualification-harness",
	}

	// Item 1: first declaration succeeds.
	if err := ledger.Declare(ctx, record); err != nil {
		t.Fatalf("first Declare: %v", err)
	}

	// Item 5: read-back timestamp matches the selected canonical precision
	// contract (RFC3339Nano) exactly -- against the REAL bucket, not a
	// local fake. This is the direct real-cloud proof that the fix's wire
	// format genuinely preserves what Unix-second encoding silently
	// dropped.
	readBack, err := ledger.readSubject(ctx, subject)
	if err != nil {
		t.Fatalf("readSubject (real GCS): %v", err)
	}
	if !readBack.EffectiveTime.Equal(now) || readBack.EffectiveTime.Nanosecond() != now.Nanosecond() {
		t.Fatalf("real-cloud read-back EffectiveTime = %v (nanosecond=%d), want %v (nanosecond=%d)",
			readBack.EffectiveTime, readBack.EffectiveTime.Nanosecond(), now, now.Nanosecond())
	}
	t.Logf("EVIDENCE: item 5 -- real-cloud read-back preserved exact nanosecond precision: stored=%d ns, read-back=%d ns", now.Nanosecond(), readBack.EffectiveTime.Nanosecond())

	// Item 2: exact duplicate is idempotent (identical EffectiveTime and
	// RecordedBy; Reason/RecordedAt may legitimately vary across retries).
	retry := record
	retry.Reason = "retry with different free-text reason"
	retry.RecordedAt = now.Add(time.Minute)
	if err := ledger.Declare(ctx, retry); err != nil {
		t.Fatalf("idempotent duplicate Declare: %v", err)
	}

	// Item 3: conflicting EffectiveTime fails closed.
	conflictingTime := record
	conflictingTime.EffectiveTime = now.Add(time.Hour)
	if err := ledger.Declare(ctx, conflictingTime); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for conflicting EffectiveTime, got: %v", err)
	}

	// Item 3 (P1 regression-specific): a duplicate differing ONLY in
	// nanoseconds (same whole second as the original `now`) must also
	// conflict against the REAL provider -- this is the exact real-cloud
	// scenario that originally exposed the P1 timestamp-precision defect
	// (Wave 2 Track C, Phase 8). Using genuine time.Now()-derived
	// nanosecond precision here, not a substitute that avoids it.
	nanosecondDifferent := record
	nanosecondDifferent.EffectiveTime = now.Add(1) // one nanosecond later, same second
	if nanosecondDifferent.EffectiveTime.Equal(now) {
		t.Fatal("test setup error: expected a genuinely different instant")
	}
	if err := ledger.Declare(ctx, nanosecondDifferent); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for a nanosecond-different EffectiveTime against the real provider, got: %v", err)
	}

	// Item 4: conflicting RecordedBy fails closed.
	conflictingRecordedBy := record
	conflictingRecordedBy.RecordedBy = "a-different-approver"
	if err := ledger.Declare(ctx, conflictingRecordedBy); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for conflicting RecordedBy, got: %v", err)
	}

	// Item 7: exact retrieval succeeds -- via Status, the only read this
	// package's public surface exposes (no separate Get; see ledger.go).
	statusAfter, err := ledger.Status(ctx, subject, now.Add(time.Second))
	if err != nil {
		t.Fatalf("Status (after distrust-effective-time): %v", err)
	}
	if statusAfter != StatusRequiresManualReview {
		t.Fatalf("Status after effective time = %v, want StatusRequiresManualReview", statusAfter)
	}

	// Item 8: missing record behaves correctly -- an entirely different
	// subject with no declaration must report StatusNotDistrusted, not an
	// error and not a false positive.
	missingSubject := subject + "-never-declared"
	statusMissing, err := ledger.Status(ctx, missingSubject, now)
	if err != nil {
		t.Fatalf("Status (missing subject): %v", err)
	}
	if statusMissing != StatusNotDistrusted {
		t.Fatalf("Status for a subject with no declaration = %v, want StatusNotDistrusted", statusMissing)
	}

	// Item 9: unavailable provider fails closed -- a Ledger pointed at a
	// bucket that does not exist must return a non-nil error from Status,
	// never silently report StatusNotDistrusted (ADR-045 §7's fail-closed
	// scope: an inability to rule out an undetected compromise is itself a
	// verification failure).
	brokenWitness := realLedgerWitness(t, bucket+"-does-not-exist-"+now.Format("150405"))
	brokenLedger, err := NewGCSLedger(brokenWitness)
	if err != nil {
		t.Fatal(err)
	}
	_, statusErr := brokenLedger.Status(ctx, subject, now)
	if statusErr == nil {
		t.Fatal("expected Status against a nonexistent bucket to fail closed with a non-nil error")
	}
	t.Logf("EVIDENCE: item 9 -- unavailable provider (nonexistent bucket) failed closed: %v", statusErr)

	t.Logf("EVIDENCE: items 1-4,7,8 pass against real GCS in a third, administratively distinct disposable project (%s)", bucket)
}

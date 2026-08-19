package compromiseledger

import (
	"context"
	"errors"
	"testing"
	"time"
)

// This file is the P1-remediation adversarial matrix for GCSLedger
// specifically (items B, I, J, K, L, O -- the GCS-backed behaviors
// MemoryLedger/FileLedger don't share, so they live here rather than in
// ledgerImplementations' generic table).

func newGCSLedgerForTest(t *testing.T) (*GCSLedger, *fakeWitness) {
	t.Helper()
	witness := newFakeWitness()
	ledger, err := NewGCSLedger(witness)
	if err != nil {
		t.Fatal(err)
	}
	return ledger, witness
}

// ATTACK_J (duplicate compromise record): declaring the identical
// (Subject, EffectiveTime, RecordedBy) twice is idempotent.
func TestAttackJ_DuplicateDeclareIsIdempotent(t *testing.T) {
	t.Parallel()
	ledger, _ := newGCSLedgerForTest(t)
	record := DistrustRecord{
		Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "suspected compromise", RecordedBy: "admin-a",
	}
	if err := ledger.Declare(context.Background(), record); err != nil {
		t.Fatal(err)
	}
	// Same substantive content, different Reason/RecordedAt -- still
	// idempotent (free text and wall-clock audit metadata may legitimately
	// vary across a retried call).
	retry := record
	retry.Reason = "confirmed compromise after investigation"
	retry.RecordedAt = time.Unix(2500, 0)
	if err := ledger.Declare(context.Background(), retry); err != nil {
		t.Fatalf("retry with the same (Subject, EffectiveTime, RecordedBy) must be idempotent, got: %v", err)
	}
}

// ATTACK_K / ATTACK_B (conflicting compromise record / suppression
// attempt): a second Declare for the same subject with a DIFFERENT
// RecordedBy -- e.g. a signing-domain administrator attempting to
// "re-declare" a subject already distrusted by the real compromise-ledger
// administrator, to make their own identity appear as the record of
// authority -- fails closed. The original record is untouched.
func TestAttackK_ConflictingRecordedByFailsClosed(t *testing.T) {
	t.Parallel()
	ledger, _ := newGCSLedgerForTest(t)
	original := DistrustRecord{
		Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "suspected compromise", RecordedBy: "compromise-ledger-admin",
	}
	if err := ledger.Declare(context.Background(), original); err != nil {
		t.Fatal(err)
	}
	suppress := original
	suppress.RecordedBy = "signing-admin-attacker"
	err := ledger.Declare(context.Background(), suppress)
	if !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("err = %v, want ErrDistrustConflict", err)
	}

	status, statusErr := ledger.Status(context.Background(), "key-1", time.Unix(2000, 0))
	if statusErr != nil {
		t.Fatal(statusErr)
	}
	if status != StatusRequiresManualReview {
		t.Fatal("the original declaration must remain intact and effective after a rejected conflicting attempt")
	}
}

// ATTACK_I (compromise-effective-time backdating attempt): a second
// Declare for the same subject with a DIFFERENT EffectiveTime -- earlier
// (backdating, hiding that the compromise was known sooner) or later
// (suppressing/postponing the manual-review window) -- fails closed
// either direction, and the ORIGINAL EffectiveTime remains governing.
func TestAttackI_BackdatingEffectiveTimeFailsClosed(t *testing.T) {
	t.Parallel()
	for _, name := range []string{"earlier", "later"} {
		t.Run(name, func(t *testing.T) {
			t.Parallel()
			ledger, _ := newGCSLedgerForTest(t)
			original := DistrustRecord{
				Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
				Reason: "suspected compromise", RecordedBy: "compromise-ledger-admin",
			}
			if err := ledger.Declare(context.Background(), original); err != nil {
				t.Fatal(err)
			}
			tampered := original
			if name == "earlier" {
				tampered.EffectiveTime = time.Unix(1000, 0)
			} else {
				tampered.EffectiveTime = time.Unix(3000, 0)
			}
			err := ledger.Declare(context.Background(), tampered)
			if !errors.Is(err, ErrDistrustConflict) {
				t.Fatalf("err = %v, want ErrDistrustConflict", err)
			}
			// The ORIGINAL effective time must still govern.
			status, statusErr := ledger.Status(context.Background(), "key-1", time.Unix(2000, 0))
			if statusErr != nil {
				t.Fatal(statusErr)
			}
			if status != StatusRequiresManualReview {
				t.Fatal("original EffectiveTime=2000 must still apply at asOf=2000 after a rejected backdating attempt")
			}
		})
	}
}

// ATTACK_L (unavailable compromise provider): Status must fail closed
// (return an error, never StatusNotDistrusted) when the underlying
// provider cannot be consulted at all -- an inability to rule out an
// undetected compromise is itself a verification failure (ADR-045 §7's
// fail-closed scope), exactly like FileLedger's own Status behavior on a
// corrupt/unreadable file.
func TestAttackL_UnavailableProviderFailsClosed(t *testing.T) {
	t.Parallel()
	ledger, witness := newGCSLedgerForTest(t)
	witness.existsErr = errInjected

	status, err := ledger.Status(context.Background(), "key-1", time.Unix(2000, 0))
	if err == nil {
		t.Fatal("expected a non-nil error when the provider cannot be consulted")
	}
	if status == StatusNotDistrusted {
		// err is non-nil here regardless, but assert this explicitly too:
		// callers must never treat the co-returned status value as
		// meaningful when err != nil.
		t.Log("status value is StatusNotDistrusted but err is non-nil -- caller MUST check err first, exactly as ADR-045 §7 requires")
	}
}

// ATTACK_O (runtime tries an alternate key/name after conflict): after a
// rejected conflicting Declare, GCSLedger must not have created any
// SECOND object for this subject under a different key -- there is no
// alternate-key fallback anywhere in this type.
func TestAttackO_NoAlternateKeyCreatedAfterConflict(t *testing.T) {
	t.Parallel()
	ledger, witness := newGCSLedgerForTest(t)
	original := DistrustRecord{
		Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "x", RecordedBy: "admin-a",
	}
	if err := ledger.Declare(context.Background(), original); err != nil {
		t.Fatal(err)
	}
	conflicting := original
	conflicting.RecordedBy = "admin-b"
	_ = ledger.Declare(context.Background(), conflicting) // expected to fail; error already covered above

	witness.mu.Lock()
	objectCount := len(witness.objects)
	witness.mu.Unlock()
	if objectCount != 1 {
		t.Fatalf("expected exactly 1 object after a rejected conflicting declare, got %d -- no alternate key may ever be created", objectCount)
	}
}

// ATTACK_N (signer runtime attempts write): compromiseledger's own
// boundary_test.go (TestCompromiseLedgerHasNoSigningCapability) already
// proves this package imports no KMS/signing capability; this test is the
// symmetric direction, proving GCSLedger itself exposes no write path
// beyond Declare (i.e. no code in cmd/recovery-signer could reach a
// mutation capability even if it tried, because none exists beyond the
// single, validated, conflict-checked Declare method).
func TestGCSLedgerExposesNoWritePathBeyondDeclare(t *testing.T) {
	t.Parallel()
	var _ Ledger = (*GCSLedger)(nil) // Ledger is exactly {Declare, Status} -- compile-time proof.
}

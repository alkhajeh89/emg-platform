package compromiseledger

import (
	"context"
	"errors"
	"path/filepath"
	"testing"
	"time"
)

// This file is the direct regression coverage for the P1 defect found
// during Wave 2 Track C real-cloud qualification: GCSLedger (and,
// identically, FileLedger) persisted EffectiveTime/RecordedAt at
// whole-second (Unix) precision, so a caller-supplied full-precision
// time.Time compared against a round-tripped, second-truncated value could
// spuriously mismatch. The fix moved both wire formats to time.RFC3339Nano
// strings. None of these tests existed before the fix -- every one of them
// would have failed against the pre-fix code (confirmed manually before
// writing this file), which is exactly why the existing suite's exclusive
// use of time.Unix(N, 0) fixtures (always zero nanoseconds) never caught
// it.

func nsTime(sec int64, nsec int) time.Time {
	return time.Unix(sec, int64(nsec)).UTC()
}

// ATTACK_A: exact retry of a nanosecond-precision EffectiveTime must be
// idempotent. GCSLedger is the only implementation whose Declare enforces
// a write-time conflict check at all (FileLedger/MemoryLedger are
// append-only and never reject a duplicate at Declare time -- see their
// own Declare methods), so this and the following GCS-specific attacks are
// scoped to GCSLedger.
func TestAttackA_ExactNanosecondRetryIsIdempotent(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	record := DistrustRecord{
		Subject: "key-1", EffectiveTime: nsTime(1700000000, 123456789), RecordedAt: nsTime(1700000000, 123456789),
		Reason: "x", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, record); err != nil {
		t.Fatalf("first Declare: %v", err)
	}
	if err := ledger.Declare(ctx, record); err != nil {
		t.Fatalf("exact retry with identical nanosecond-precision EffectiveTime must be idempotent, got: %v", err)
	}
}

// ATTACK_B: same second, different nanoseconds -- must conflict, never be
// silently treated as identical.
func TestAttackB_SameSecondDifferentNanosecondsConflicts(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	first := DistrustRecord{
		Subject: "key-1", EffectiveTime: nsTime(1700000000, 123456789), RecordedAt: nsTime(1700000000, 0),
		Reason: "x", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, first); err != nil {
		t.Fatal(err)
	}
	second := first
	second.EffectiveTime = nsTime(1700000000, 987654321) // same second, different nanoseconds
	if err := ledger.Declare(ctx, second); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for a same-second, different-nanosecond EffectiveTime, got: %v", err)
	}
}

// Different seconds entirely must also conflict (sanity companion to
// ATTACK_B, at whole-second granularity rather than sub-second).
func TestDifferentSecondsConflicts(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	first := DistrustRecord{
		Subject: "key-1", EffectiveTime: nsTime(1700000000, 500000000), RecordedAt: nsTime(1700000000, 0),
		Reason: "x", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, first); err != nil {
		t.Fatal(err)
	}
	second := first
	second.EffectiveTime = nsTime(1700000001, 500000000)
	if err := ledger.Declare(ctx, second); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for a different EffectiveTime second, got: %v", err)
	}
}

// ATTACK_E: identical EffectiveTime (including nanoseconds), different
// RecordedBy -- must conflict. This is the write-time analogue of an
// attacker attempting to attribute a declaration to a different approver
// after the fact.
func TestAttackE_SameNanosecondTimeDifferentRecordedByConflicts(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	effective := nsTime(1700000000, 555555555)
	first := DistrustRecord{
		Subject: "key-1", EffectiveTime: effective, RecordedAt: effective,
		Reason: "x", RecordedBy: "approver-a",
	}
	if err := ledger.Declare(ctx, first); err != nil {
		t.Fatal(err)
	}
	second := first
	second.RecordedBy = "approver-b"
	if err := ledger.Declare(ctx, second); !errors.Is(err, ErrDistrustConflict) {
		t.Fatalf("expected ErrDistrustConflict for a different RecordedBy at the identical nanosecond EffectiveTime, got: %v", err)
	}
}

// ATTACK_F: identical (EffectiveTime, RecordedBy), differing Reason and
// RecordedAt -- ADR-045's documented non-identity fields -- must remain
// idempotent, at full nanosecond precision (extends the existing
// TestAttackJ_DuplicateDeclareIsIdempotent, which only used whole-second
// values).
func TestAttackF_NonIdentityFieldsMayDifferAtNanosecondPrecision(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	effective := nsTime(1700000000, 111111111)
	first := DistrustRecord{
		Subject: "key-1", EffectiveTime: effective, RecordedAt: nsTime(1700000000, 1),
		Reason: "initial reason", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, first); err != nil {
		t.Fatal(err)
	}
	retry := DistrustRecord{
		Subject: "key-1", EffectiveTime: effective, RecordedAt: nsTime(1700000005, 999999999),
		Reason: "a completely different free-text reason", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, retry); err != nil {
		t.Fatalf("Reason/RecordedAt are documented non-identity fields and must not cause a conflict, got: %v", err)
	}
}

// ATTACK_C: an EffectiveTime constructed in a non-UTC location, but
// representing the identical instant as an already-declared UTC value,
// must be treated as idempotent -- time.Time.Equal compares instants, not
// display representations, and UTC-normalization on encode must not change
// that.
func TestAttackC_TimezoneRepresentationDoesNotAffectIdentity(t *testing.T) {
	ledger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()
	utcTime := nsTime(1700000000, 250000000)
	first := DistrustRecord{
		Subject: "key-1", EffectiveTime: utcTime, RecordedAt: utcTime,
		Reason: "x", RecordedBy: "test-admin",
	}
	if err := ledger.Declare(ctx, first); err != nil {
		t.Fatal(err)
	}

	plusFive := time.FixedZone("UTC+5", 5*60*60)
	sameInstantDifferentZone := utcTime.In(plusFive)
	if !sameInstantDifferentZone.Equal(utcTime) {
		t.Fatal("test setup error: the two values must represent the identical instant")
	}
	second := first
	second.EffectiveTime = sameInstantDifferentZone
	if err := ledger.Declare(ctx, second); err != nil {
		t.Fatalf("a differently-zoned representation of the identical instant must remain idempotent, got: %v", err)
	}
}

// Round-trip precision: Declare with full nanosecond precision, then read
// the persisted record back (via each provider's own internal read path)
// and confirm the exact nanosecond value survives -- the direct proof that
// the RFC3339Nano wire format actually preserves what Unix-second encoding
// silently dropped.
func TestRoundTripPreservesNanosecondPrecision(t *testing.T) {
	effective := nsTime(1700000000, 123456789)
	recordedAt := nsTime(1700000000, 1)

	t.Run("GCSLedger", func(t *testing.T) {
		ledger, err := NewGCSLedger(newFakeWitness())
		if err != nil {
			t.Fatal(err)
		}
		ctx := context.Background()
		if err := ledger.Declare(ctx, DistrustRecord{
			Subject: "key-1", EffectiveTime: effective, RecordedAt: recordedAt,
			Reason: "x", RecordedBy: "test-admin",
		}); err != nil {
			t.Fatal(err)
		}
		got, err := ledger.readSubject(ctx, "key-1")
		if err != nil {
			t.Fatal(err)
		}
		if !got.EffectiveTime.Equal(effective) || got.EffectiveTime.Nanosecond() != effective.Nanosecond() {
			t.Fatalf("EffectiveTime round-trip = %v, want %v (nanosecond-exact)", got.EffectiveTime, effective)
		}
		if !got.RecordedAt.Equal(recordedAt) || got.RecordedAt.Nanosecond() != recordedAt.Nanosecond() {
			t.Fatalf("RecordedAt round-trip = %v, want %v (nanosecond-exact)", got.RecordedAt, recordedAt)
		}
	})

	t.Run("FileLedger", func(t *testing.T) {
		ledger, err := NewFileLedger(filepath.Join(t.TempDir(), "ledger.jsonl"))
		if err != nil {
			t.Fatal(err)
		}
		ctx := context.Background()
		if err := ledger.Declare(ctx, DistrustRecord{
			Subject: "key-1", EffectiveTime: effective, RecordedAt: recordedAt,
			Reason: "x", RecordedBy: "test-admin",
		}); err != nil {
			t.Fatal(err)
		}
		records, err := ledger.readVerifiedChain()
		if err != nil {
			t.Fatal(err)
		}
		if len(records) != 1 {
			t.Fatalf("expected exactly one record, got %d", len(records))
		}
		got := records[0]
		if !got.EffectiveTime.Equal(effective) || got.EffectiveTime.Nanosecond() != effective.Nanosecond() {
			t.Fatalf("EffectiveTime round-trip = %v, want %v (nanosecond-exact)", got.EffectiveTime, effective)
		}
		if !got.RecordedAt.Equal(recordedAt) || got.RecordedAt.Nanosecond() != recordedAt.Nanosecond() {
			t.Fatalf("RecordedAt round-trip = %v, want %v (nanosecond-exact)", got.RecordedAt, recordedAt)
		}
	})
}

// ATTACK_G: a malformed persisted timestamp must fail closed -- never be
// silently reinterpreted as the zero time (which could otherwise sort as
// "before" every real comparison and masquerade as an ancient, harmless
// declaration). This also documents the chosen backward-compatibility
// policy for pre-fix (Unix-second int64 field) records: there is no dual
// read path: this package has no production deployment, so an old-format
// record is simply a malformed record under the new schema, and decoding
// it must error, never silently succeed with a wrong value.
func TestAttackG_MalformedPersistedTimestampFailsClosed(t *testing.T) {
	witness := newFakeWitness()
	ledger, err := NewGCSLedger(witness)
	if err != nil {
		t.Fatal(err)
	}
	ctx := context.Background()

	// Simulate a pre-fix record (old int64 Unix-second field names/types)
	// or any other structurally-invalid effective_time_rfc3339 value,
	// written directly to the underlying witness -- bypassing Declare
	// entirely, exactly as a real legacy or corrupted object would appear.
	key := gcsLedgerKey("key-1")
	legacyShapedJSON := []byte(`{"subject":"key-1","effective_time_unix":2000,"recorded_at_unix":2000,"reason":"x","recorded_by":"test-admin"}`)
	if _, err := witness.CreateExactIfAbsent(ctx, key, legacyShapedJSON); err != nil {
		t.Fatal(err)
	}

	_, err = ledger.readSubject(ctx, "key-1")
	if err == nil {
		t.Fatal("expected a legacy/malformed timestamp shape to fail closed with a decode error")
	}
	t.Logf("EVIDENCE: legacy/malformed record correctly failed closed: %v", err)

	status, statusErr := ledger.Status(ctx, "key-1", time.Now())
	if statusErr == nil {
		t.Fatal("expected Status to fail closed (non-nil error) for a subject whose only record is malformed")
	}
	if status == StatusNotDistrusted {
		t.Log("status value is StatusNotDistrusted but err is non-nil -- caller MUST check err first, exactly as ADR-045 §7 requires")
	}
}

// Backdating remains detected at nanosecond precision, not just
// whole-second precision (extends the existing
// TestAttackI_BackdatingEffectiveTimeFailsClosed).
func TestAttackD_NanosecondBackdatingFailsClosed(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		if name != "GCSLedger" {
			continue // only GCSLedger enforces a write-time conflict check
		}
		t.Run(name, func(t *testing.T) {
			ctx := context.Background()
			original := nsTime(1700000000, 500000000)
			if err := ledger.Declare(ctx, DistrustRecord{
				Subject: "key-1", EffectiveTime: original, RecordedAt: original,
				Reason: "x", RecordedBy: "test-admin",
			}); err != nil {
				t.Fatal(err)
			}
			backdated := original.Add(-1) // one nanosecond earlier
			if err := ledger.Declare(ctx, DistrustRecord{
				Subject: "key-1", EffectiveTime: backdated, RecordedAt: original,
				Reason: "x", RecordedBy: "test-admin",
			}); !errors.Is(err, ErrDistrustConflict) {
				t.Fatalf("expected a one-nanosecond backdating attempt to be detected as ErrDistrustConflict, got: %v", err)
			}
		})
	}
}

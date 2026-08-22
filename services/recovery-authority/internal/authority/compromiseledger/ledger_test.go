package compromiseledger

import (
	"bytes"
	"context"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness"
)

// fakeWitness is an in-memory gcswitness.ImmutableWitness with the same
// create-if-absent/no-overwrite semantics as the real adapter -- used only
// to exercise GCSLedger's own logic against a real ImmutableWitness
// implementation, without any network or GCP dependency.
type fakeWitness struct {
	mu        sync.Mutex
	objects   map[string][]byte
	existsErr error
}

func newFakeWitness() *fakeWitness { return &fakeWitness{objects: make(map[string][]byte)} }

var errInjected = errors.New("compromiseledger_test: injected provider failure")

func (f *fakeWitness) Exists(_ context.Context, key string) (bool, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.existsErr != nil {
		return false, f.existsErr
	}
	_, ok := f.objects[key]
	return ok, nil
}

func (f *fakeWitness) ReadExact(_ context.Context, key string) ([]byte, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	value, ok := f.objects[key]
	if !ok {
		return nil, gcswitness.ErrNotFound
	}
	return append([]byte(nil), value...), nil
}

func (f *fakeWitness) CreateExactIfAbsent(_ context.Context, key string, payload []byte) (gcswitness.CreateOutcome, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	existing, ok := f.objects[key]
	if ok {
		if bytes.Equal(existing, payload) {
			return gcswitness.AlreadyExistsIdentical, nil
		}
		return gcswitness.AlreadyExistsConflict, gcswitness.ErrConflict
	}
	f.objects[key] = append([]byte(nil), payload...)
	return gcswitness.CreateSuccess, nil
}

var _ gcswitness.ImmutableWitness = (*fakeWitness)(nil)

func ledgerImplementations(t *testing.T) map[string]Ledger {
	t.Helper()
	fileLedger, err := NewFileLedger(filepath.Join(t.TempDir(), "ledger.jsonl"))
	if err != nil {
		t.Fatal(err)
	}
	gcsLedger, err := NewGCSLedger(newFakeWitness())
	if err != nil {
		t.Fatal(err)
	}
	return map[string]Ledger{
		"MemoryLedger": NewMemoryLedger(),
		"FileLedger":   fileLedger,
		"GCSLedger":    gcsLedger,
	}
}

func mustDeclare(t *testing.T, ledger Ledger, record DistrustRecord) {
	t.Helper()
	if err := ledger.Declare(context.Background(), record); err != nil {
		t.Fatal(err)
	}
}

func TestStatusNotDistrustedWithNoDeclarations(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		t.Run(name, func(t *testing.T) {
			status, err := ledger.Status(context.Background(), "key-1", time.Unix(1000, 0))
			if err != nil {
				t.Fatal(err)
			}
			if status != StatusNotDistrusted {
				t.Fatalf("status = %v, want StatusNotDistrusted", status)
			}
		})
	}
}

// TestStatusBeforeEffectiveTimeRemainsTrusted is qualification requirement
// 14 (ADR-045 §18): a record strictly before the distrust-effective-time
// remains governed by ordinary verification, not silently treated as
// compromised merely because the key was later distrusted.
func TestStatusBeforeEffectiveTimeRemainsTrusted(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		t.Run(name, func(t *testing.T) {
			mustDeclare(t, ledger, DistrustRecord{
				Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
				Reason: "suspected compromise", RecordedBy: "test-admin",
			})
			status, err := ledger.Status(context.Background(), "key-1", time.Unix(1000, 0))
			if err != nil {
				t.Fatal(err)
			}
			if status != StatusNotDistrusted {
				t.Fatalf("status = %v, want StatusNotDistrusted for a record strictly before the distrust-effective-time", status)
			}
		})
	}
}

// TestStatusAtOrAfterEffectiveTimeRequiresManualReview is qualification
// requirement 13 (ADR-045 §18): a record at or after the distrust-effective
// time is never auto-accepted.
func TestStatusAtOrAfterEffectiveTimeRequiresManualReview(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		t.Run(name, func(t *testing.T) {
			mustDeclare(t, ledger, DistrustRecord{
				Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
				Reason: "suspected compromise", RecordedBy: "test-admin",
			})
			// Exactly at EffectiveTime.
			status, err := ledger.Status(context.Background(), "key-1", time.Unix(2000, 0))
			if err != nil {
				t.Fatal(err)
			}
			if status != StatusRequiresManualReview {
				t.Fatalf("status at EffectiveTime = %v, want StatusRequiresManualReview", status)
			}
			// After EffectiveTime.
			status, err = ledger.Status(context.Background(), "key-1", time.Unix(3000, 0))
			if err != nil {
				t.Fatal(err)
			}
			if status != StatusRequiresManualReview {
				t.Fatalf("status after EffectiveTime = %v, want StatusRequiresManualReview", status)
			}
		})
	}
}

func TestStatusIsSubjectScoped(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		t.Run(name, func(t *testing.T) {
			mustDeclare(t, ledger, DistrustRecord{
				Subject: "key-distrusted", EffectiveTime: time.Unix(1000, 0), RecordedAt: time.Unix(1000, 0),
				Reason: "x", RecordedBy: "test-admin",
			})
			status, err := ledger.Status(context.Background(), "key-unrelated", time.Unix(5000, 0))
			if err != nil {
				t.Fatal(err)
			}
			if status != StatusNotDistrusted {
				t.Fatalf("an unrelated subject's status must be unaffected by another subject's distrust declaration, got %v", status)
			}
		})
	}
}

func TestDeclareRejectsIncompleteRecord(t *testing.T) {
	for name, ledger := range ledgerImplementations(t) {
		t.Run(name, func(t *testing.T) {
			cases := []DistrustRecord{
				{EffectiveTime: time.Unix(1, 0), RecordedBy: "x"}, // missing Subject
				{Subject: "k", RecordedBy: "x"},                   // missing EffectiveTime
				{Subject: "k", EffectiveTime: time.Unix(1, 0)},    // missing RecordedBy
			}
			for _, record := range cases {
				if err := ledger.Declare(context.Background(), record); err == nil {
					t.Errorf("expected incomplete record %+v to be rejected", record)
				}
			}
		})
	}
}

// TestFileLedgerDetectsTamperedRecord proves the hash chain catches an
// in-place edit of an existing record -- the direct regression test for
// ADR-045 §7 property 4 ("protected against unilateral deletion,
// suppression, or backdating").
func TestFileLedgerDetectsTamperedRecord(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ledger.jsonl")
	ledger, err := NewFileLedger(path)
	if err != nil {
		t.Fatal(err)
	}
	mustDeclare(t, ledger, DistrustRecord{
		Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "x", RecordedBy: "test-admin",
	})
	mustDeclare(t, ledger, DistrustRecord{
		Subject: "key-2", EffectiveTime: time.Unix(3000, 0), RecordedAt: time.Unix(3000, 0),
		Reason: "y", RecordedBy: "test-admin",
	})

	// Tamper: backdate the first record's effective time directly in the
	// file, simulating a malicious signing-domain administrator attempting
	// to suppress a distrust declaration by moving its effective time
	// later (or earlier) without going through Declare.
	raw, err := os.ReadFile(path)
	if err != nil {
		t.Fatal(err)
	}
	tampered := append([]byte{}, raw...)
	// Flip a byte inside the first line's effective_time_rfc3339 digits.
	for i, b := range tampered {
		if b == '2' {
			tampered[i] = '9'
			break
		}
	}
	if err := os.WriteFile(path, tampered, 0o600); err != nil {
		t.Fatal(err)
	}

	if _, err := NewFileLedger(path); err == nil {
		t.Fatal("expected re-opening a tampered ledger file to fail its chain-integrity check")
	}
}

func TestFileLedgerPersistsAcrossReopen(t *testing.T) {
	path := filepath.Join(t.TempDir(), "ledger.jsonl")
	first, err := NewFileLedger(path)
	if err != nil {
		t.Fatal(err)
	}
	mustDeclare(t, first, DistrustRecord{
		Subject: "key-1", EffectiveTime: time.Unix(2000, 0), RecordedAt: time.Unix(2000, 0),
		Reason: "x", RecordedBy: "test-admin",
	})

	reopened, err := NewFileLedger(path)
	if err != nil {
		t.Fatal(err)
	}
	status, err := reopened.Status(context.Background(), "key-1", time.Unix(2000, 0))
	if err != nil {
		t.Fatal(err)
	}
	if status != StatusRequiresManualReview {
		t.Fatalf("status after reopen = %v, want StatusRequiresManualReview", status)
	}
}

func TestEvaluateStatusMultipleDeclarationsUsesEarliestApplicable(t *testing.T) {
	records := []DistrustRecord{
		{Subject: "key-1", EffectiveTime: time.Unix(5000, 0)},
		{Subject: "key-1", EffectiveTime: time.Unix(2000, 0)},
	}
	status := EvaluateStatus(records, "key-1", time.Unix(3000, 0))
	if status != StatusRequiresManualReview {
		t.Fatalf("status = %v, want StatusRequiresManualReview -- the earlier (2000) declaration already applies at asOf=3000", status)
	}
}

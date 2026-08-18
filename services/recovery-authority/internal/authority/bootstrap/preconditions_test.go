package bootstrap

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/compromiseledger"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestCheckSigningPreconditionsPassesOnFullyValidSetup(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	pre := SigningPreconditions{Lineage: fx.lineage, PinStore: fx.pinStore, Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestCheckSigningPreconditionsRequiresLineage(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	pre := SigningPreconditions{Lineage: nil, PinStore: fx.pinStore, Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrLineageNotConfigured) {
		t.Fatalf("err = %v, want ErrLineageNotConfigured", err)
	}
}

// TestCheckSigningPreconditionsRejectsKeyOutsideLineage is ATTACK_C:
// unapproved signing lineage.
func TestCheckSigningPreconditionsRejectsKeyOutsideLineage(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	otherLineage, err := keypinning.CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/different-key")
	if err != nil {
		t.Fatal(err)
	}
	pre := SigningPreconditions{Lineage: otherLineage, PinStore: fx.pinStore, Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrKeyNotInLineage) {
		t.Fatalf("err = %v, want ErrKeyNotInLineage", err)
	}
}

// TestCheckSigningPreconditionsRejectsUnpinnedKey is ATTACK_D: missing key
// pin.
func TestCheckSigningPreconditionsRejectsUnpinnedKey(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	pre := SigningPreconditions{Lineage: fx.lineage, PinStore: keypinning.NewMemoryStore(), Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrKeyNotPinned) {
		t.Fatalf("err = %v, want ErrKeyNotPinned", err)
	}
}

// TestCheckSigningPreconditionsRejectsUnavailableLedger is ATTACK_E:
// compromise ledger unavailable.
func TestCheckSigningPreconditionsRejectsUnavailableLedger(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	pre := SigningPreconditions{Lineage: fx.lineage, PinStore: fx.pinStore, Ledger: nil, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrCompromiseLedgerUnavailable) {
		t.Fatalf("err = %v, want ErrCompromiseLedgerUnavailable", err)
	}
}

func TestCheckSigningPreconditionsRejectsDistrustedKey(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	if err := fx.ledger.Declare(context.Background(), compromiseledger.DistrustRecord{
		Subject:       compromiseledger.SigningKeyIDSubject(fx.keyID),
		EffectiveTime: time.Now().UTC().Add(-time.Hour),
		RecordedAt:    time.Now().UTC(),
		Reason:        "test distrust",
		RecordedBy:    "test",
	}); err != nil {
		t.Fatal(err)
	}
	pre := SigningPreconditions{Lineage: fx.lineage, PinStore: fx.pinStore, Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrKeyRequiresManualReview) {
		t.Fatalf("err = %v, want ErrKeyRequiresManualReview", err)
	}
}

// TestCheckSigningPreconditionsRejectsSignerKeyMismatch proves genesis
// refuses to proceed when the live signer's active key disagrees with the
// requested, already-vetted key -- signer/verifier must agree on key
// identity (S6 Phase 5).
func TestCheckSigningPreconditionsRejectsSignerKeyMismatch(t *testing.T) {
	t.Parallel()
	fx := newTestFixture(t)
	otherKeyID, err := protocol.NewSigningKeyID(testCryptoKey + "/cryptoKeyVersions/9")
	if err != nil {
		t.Fatal(err)
	}
	fx.signer.keyID = otherKeyID
	pre := SigningPreconditions{Lineage: fx.lineage, PinStore: fx.pinStore, Ledger: fx.ledger, Signer: fx.signer}
	if err := CheckSigningPreconditions(context.Background(), pre, fx.keyID); !errors.Is(err, ErrSignerKeyMismatch) {
		t.Fatalf("err = %v, want ErrSignerKeyMismatch", err)
	}
}

func TestCheckWitnessPreconditionsReportsAbsence(t *testing.T) {
	t.Parallel()
	witness := newFakeWitness()
	exists, err := CheckWitnessPreconditions(context.Background(), WitnessPreconditions{Witness: witness}, "some-key")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if exists {
		t.Fatal("expected exists=false for an empty witness store")
	}
}

func TestCheckWitnessPreconditionsFailsClosedOnAmbiguousExists(t *testing.T) {
	t.Parallel()
	witness := newFakeWitness()
	witness.forceExistsErr = errInjected
	_, err := CheckWitnessPreconditions(context.Background(), WitnessPreconditions{Witness: witness}, "some-key")
	if !errors.Is(err, ErrWitnessTargetUnavailable) {
		t.Fatalf("err = %v, want ErrWitnessTargetUnavailable", err)
	}
}

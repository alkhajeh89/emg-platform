package keypinning

import (
	"context"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func TestSafeToDisableTrueOnlyAfterConfirmedPin(t *testing.T) {
	_, pemStr := generateECDSATestKey(t)
	store := NewMemoryStore()
	keyID := testSigningKeyID(t, "rotate-1")

	safe, err := SafeToDisable(context.Background(), store, keyID, pemStr)
	if err != nil {
		t.Fatal(err)
	}
	if safe {
		t.Fatal("must not be safe to disable before any pin exists")
	}

	if err := store.Pin(context.Background(), testPin(t, keyID, pemStr)); err != nil {
		t.Fatal(err)
	}
	safe, err = SafeToDisable(context.Background(), store, keyID, pemStr)
	if err != nil {
		t.Fatal(err)
	}
	if !safe {
		t.Fatal("must be safe to disable once the exact expected material is confirmed pinned")
	}
}

func TestSafeToDisableFalseOnMaterialMismatch(t *testing.T) {
	_, pemA := generateECDSATestKey(t)
	_, pemB := generateECDSATestKey(t)
	store := NewMemoryStore()
	keyID := testSigningKeyID(t, "rotate-2")
	if err := store.Pin(context.Background(), testPin(t, keyID, pemA)); err != nil {
		t.Fatal(err)
	}
	safe, err := SafeToDisable(context.Background(), store, keyID, pemB)
	if err != nil {
		t.Fatal(err)
	}
	if safe {
		t.Fatal("must not report safe when the pinned material differs from what the caller expects")
	}
}

func TestSafeToDisableRejectsZeroKeyID(t *testing.T) {
	if _, err := SafeToDisable(context.Background(), NewMemoryStore(), protocol.SigningKeyID{}, "x"); err == nil {
		t.Fatal("expected zero SigningKeyID to be rejected")
	}
}

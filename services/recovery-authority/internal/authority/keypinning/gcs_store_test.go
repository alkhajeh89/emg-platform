package keypinning

import (
	"context"
	"testing"
)

// This file is the P1-remediation adversarial matrix for GCSStore
// specifically (items A/D/E/O -- conflict/no-alternate-key behaviors
// MemoryStore/FileStore don't share a GCS-backed provider with, so they
// are re-proven here directly against the real ImmutableWitness-composed
// implementation, in addition to the shared-table tests in store_test.go).

// ATTACK_A / ATTACK_D / ATTACK_E (signer/pin-capture admin attempts pin
// replacement / overwrite / conflicting bytes at the same identity): the
// direct GCSStore-specific counterpart to
// TestStoreDifferentMaterialUnderSameKeyIDFailsClosed, confirming the
// original pin's bytes in the underlying witness are byte-for-byte
// unchanged after a rejected conflicting Pin call -- not merely that Get
// still returns the right value, but that no second write ever reached
// the provider.
func TestAttackADE_GCSStoreConflictNeverMutatesUnderlyingObject(t *testing.T) {
	t.Parallel()
	witness := newFakeWitness()
	store, err := NewGCSStore(witness)
	if err != nil {
		t.Fatal(err)
	}
	_, pemA := generateECDSATestKey(t)
	_, pemB := generateECDSATestKey(t)
	keyID := testSigningKeyID(t, "conflict")

	if err := store.Pin(context.Background(), testPin(t, keyID, pemA)); err != nil {
		t.Fatal(err)
	}
	key := filenameFor(keyID)
	witness.mu.Lock()
	originalBytes := append([]byte(nil), witness.objects[key]...)
	witness.mu.Unlock()

	if err := store.Pin(context.Background(), testPin(t, keyID, pemB)); err == nil {
		t.Fatal("expected ErrPinConflict")
	}

	witness.mu.Lock()
	afterBytes := witness.objects[key]
	objectCount := len(witness.objects)
	witness.mu.Unlock()
	if string(afterBytes) != string(originalBytes) {
		t.Fatal("the underlying stored object must be byte-for-byte unchanged after a rejected conflicting Pin")
	}
	// ATTACK_O: no alternate key was created for the rejected attempt.
	if objectCount != 1 {
		t.Fatalf("expected exactly 1 object after a rejected conflicting pin, got %d -- no alternate key may ever be created", objectCount)
	}
}

// Store's own method set is exactly {Pin, Get} -- a compile-time proof
// that the interface itself cannot be widened without also widening every
// existing implementation (MemoryStore, FileStore, GCSStore) at the same
// time. The source-level scan for forbidden method-name substrings
// (ATTACK_P: delete/update API accidentally exposed) lives in
// boundary_test.go, mirroring compromiseledger's
// TestCompromiseLedgerHasNoMutationMethod exactly.
func TestStoreInterfaceIsSatisfiedByAllThreeImplementations(t *testing.T) {
	t.Parallel()
	var _ Store = (*MemoryStore)(nil)
	var _ Store = (*FileStore)(nil)
	var _ Store = (*GCSStore)(nil)
}

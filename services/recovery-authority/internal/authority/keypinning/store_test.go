package keypinning

import (
	"context"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

func testSigningKeyID(t *testing.T, suffix string) protocol.SigningKeyID {
	t.Helper()
	id, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/" + suffix)
	if err != nil {
		t.Fatal(err)
	}
	return id
}

func keyIDFor(t *testing.T, value string) (protocol.SigningKeyID, error) {
	t.Helper()
	return protocol.NewSigningKeyID(value)
}

func testPin(t *testing.T, keyID protocol.SigningKeyID, pemMaterial string) PinnedKey {
	t.Helper()
	pin, err := newValidatedPin(keyID, AlgorithmECSignP256SHA256, pemMaterial, "test", time.Unix(1000, 0).UTC())
	if err != nil {
		t.Fatal(err)
	}
	return pin
}

func storeImplementations(t *testing.T) map[string]Store {
	t.Helper()
	return map[string]Store{
		"MemoryStore": NewMemoryStore(),
		"FileStore": func() Store {
			s, err := NewFileStore(t.TempDir())
			if err != nil {
				t.Fatal(err)
			}
			return s
		}(),
	}
}

func TestStorePinThenGetRoundTrips(t *testing.T) {
	_, pemA := generateECDSATestKey(t)
	for name, store := range storeImplementations(t) {
		t.Run(name, func(t *testing.T) {
			keyID := testSigningKeyID(t, "1")
			pin := testPin(t, keyID, pemA)
			if err := store.Pin(context.Background(), pin); err != nil {
				t.Fatal(err)
			}
			got, err := store.Get(context.Background(), keyID)
			if err != nil {
				t.Fatal(err)
			}
			if got.PublicKeyPEM != pemA {
				t.Fatal("round-tripped public key material does not match")
			}
		})
	}
}

func TestStoreGetUnknownKeyFailsClosed(t *testing.T) {
	for name, store := range storeImplementations(t) {
		t.Run(name, func(t *testing.T) {
			_, err := store.Get(context.Background(), testSigningKeyID(t, "unknown"))
			if err == nil {
				t.Fatal("expected ErrPinNotFound for an unpinned key")
			}
		})
	}
}

func TestStoreIdenticalRepinIsIdempotent(t *testing.T) {
	_, pemA := generateECDSATestKey(t)
	for name, store := range storeImplementations(t) {
		t.Run(name, func(t *testing.T) {
			keyID := testSigningKeyID(t, "2")
			pin := testPin(t, keyID, pemA)
			if err := store.Pin(context.Background(), pin); err != nil {
				t.Fatal(err)
			}
			if err := store.Pin(context.Background(), pin); err != nil {
				t.Fatalf("identical re-pin must be idempotent, got: %v", err)
			}
		})
	}
}

// TestStoreDifferentMaterialUnderSameKeyIDFailsClosed is the direct
// regression test for ADR-045 §7C's integrity requirement: a pinned public
// key cannot be silently swapped for a different key under the same
// SigningKeyID (Attack 22).
func TestStoreDifferentMaterialUnderSameKeyIDFailsClosed(t *testing.T) {
	_, pemA := generateECDSATestKey(t)
	_, pemB := generateECDSATestKey(t)
	for name, store := range storeImplementations(t) {
		t.Run(name, func(t *testing.T) {
			keyID := testSigningKeyID(t, "3")
			if err := store.Pin(context.Background(), testPin(t, keyID, pemA)); err != nil {
				t.Fatal(err)
			}
			err := store.Pin(context.Background(), testPin(t, keyID, pemB))
			if err == nil {
				t.Fatal("expected ErrPinConflict when different material is pinned under an existing SigningKeyID")
			}
			// The original pin must remain intact and readable.
			got, getErr := store.Get(context.Background(), keyID)
			if getErr != nil {
				t.Fatal(getErr)
			}
			if got.PublicKeyPEM != pemA {
				t.Fatal("original pin was corrupted by a rejected conflicting pin attempt")
			}
		})
	}
}

func TestNewValidatedPinRejectsZeroKeyID(t *testing.T) {
	if _, err := newValidatedPin(protocol.SigningKeyID{}, AlgorithmECSignP256SHA256, "x", "", time.Now()); err == nil {
		t.Fatal("expected zero SigningKeyID to be rejected")
	}
}

func TestNewValidatedPinRejectsUnsupportedAlgorithm(t *testing.T) {
	_, pem := generateECDSATestKey(t)
	if _, err := newValidatedPin(testSigningKeyID(t, "4"), "EC_SIGN_P384_SHA384", pem, "", time.Now()); err == nil {
		t.Fatal("expected unsupported algorithm to be rejected")
	}
}

func TestNewValidatedPinRejectsMalformedPublicKey(t *testing.T) {
	if _, err := newValidatedPin(testSigningKeyID(t, "5"), AlgorithmECSignP256SHA256, "not a pem", "", time.Now()); err == nil {
		t.Fatal("expected malformed public key material to be rejected")
	}
}

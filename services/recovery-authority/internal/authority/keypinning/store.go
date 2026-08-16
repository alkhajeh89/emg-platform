package keypinning

import (
	"context"
	"errors"
	"sync"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// ErrPinConflict means a pin already exists for this SigningKeyID with
// DIFFERENT public key material than what is being pinned now. This is the
// fail-closed integrity gate required by ADR-045 §7C ("an integrity binding
// between the SigningKeyID and the pinned public key, so the pinned copy
// cannot be silently swapped for a different key under the same
// identifier"). Re-pinning byte-identical material for an already-pinned
// SigningKeyID is idempotent and never returns this error.
var ErrPinConflict = errors.New("keypinning: a different public key is already pinned for this SigningKeyID")

// ErrPinNotFound means no pin exists for the requested SigningKeyID. Every
// caller in this codebase MUST treat this as fail-closed -- historical
// verification of a key with no pinned material must not proceed (ADR-045
// §7C, Attack 21).
var ErrPinNotFound = errors.New("keypinning: no pin exists for this SigningKeyID")

// Store durably persists PinnedKey records. Every implementation MUST:
//   - reject (ErrPinConflict) an attempt to pin different material under an
//     already-pinned SigningKeyID;
//   - accept idempotently a re-pin of byte-identical material;
//   - never allow deletion or mutation of an existing pin through this
//     interface -- there is deliberately no Delete or Update method.
type Store interface {
	// Pin durably records pin. Fails closed with ErrPinConflict on a
	// material mismatch against an existing pin for the same SigningKeyID.
	Pin(ctx context.Context, pin PinnedKey) error
	// Get retrieves the pin for keyID. Returns ErrPinNotFound if none
	// exists. Implementations MUST recompute and verify the fingerprint
	// against the stored material before returning it, never trusting a
	// stored fingerprint value alone.
	Get(ctx context.Context, keyID protocol.SigningKeyID) (PinnedKey, error)
}

// MemoryStore is a non-durable, integrity-checked Store for unit tests. It
// is NOT suitable for qualification or production use (no durability across
// process restarts) -- see FileStore for that tier.
type MemoryStore struct {
	mu   sync.Mutex
	pins map[string]PinnedKey
}

func NewMemoryStore() *MemoryStore {
	return &MemoryStore{pins: make(map[string]PinnedKey)}
}

func (s *MemoryStore) Pin(_ context.Context, pin PinnedKey) error {
	if pin.SigningKeyID.IsZero() {
		return ErrPinRequiresSigningKeyID
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	existing, found := s.pins[pin.SigningKeyID.String()]
	if found && existing.Fingerprint != pin.Fingerprint {
		return ErrPinConflict
	}
	s.pins[pin.SigningKeyID.String()] = pin
	return nil
}

func (s *MemoryStore) Get(_ context.Context, keyID protocol.SigningKeyID) (PinnedKey, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	pin, found := s.pins[keyID.String()]
	if !found {
		return PinnedKey{}, ErrPinNotFound
	}
	if computeFingerprint(pin.PublicKeyPEM) != pin.Fingerprint {
		return PinnedKey{}, errors.New("keypinning: stored pin failed integrity check -- fingerprint does not match material")
	}
	return pin, nil
}

var _ Store = (*MemoryStore)(nil)

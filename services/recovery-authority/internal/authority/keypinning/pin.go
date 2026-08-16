package keypinning

import (
	"crypto/sha256"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// PinnedKey is one durably preserved, integrity-protected public-key pin
// (ADR-045 §7C). It preserves exactly what §7C requires and nothing more:
// the immutable SigningKeyID; the public verification material itself; the
// algorithm/key-metadata required to correctly interpret it; an integrity
// fingerprint binding the SigningKeyID to this exact public key (so a
// PinnedKey record cannot be silently replaced under the same identifier);
// and provenance evidence of where the material was captured from.
type PinnedKey struct {
	SigningKeyID protocol.SigningKeyID
	Algorithm    Algorithm
	// PublicKeyPEM is the PEM-encoded SubjectPublicKeyInfo, exactly as
	// returned by the provider's public-key-retrieval call. Public material
	// only -- never private key bytes (see ParsePEMPublicKey).
	PublicKeyPEM string
	// Fingerprint is SHA-256(PublicKeyPEM), recomputed independently at
	// every read (never trusted from storage alone) to detect any silent
	// substitution of the pinned material for a given SigningKeyID.
	Fingerprint [32]byte
	PinnedAt    time.Time
	// Provenance records where this pin was captured from -- e.g. which
	// approved CryptoKey lineage prefix it was captured under, and by what
	// mechanism. Free-text audit context, not itself a trust decision.
	Provenance string
}

// ErrPinRequiresSigningKeyID and friends validate a PinnedKey's required
// fields before it may be stored.
var (
	ErrPinRequiresSigningKeyID = errors.New("keypinning: pin requires a non-zero SigningKeyID")
	ErrPinRequiresPublicKey    = errors.New("keypinning: pin requires non-empty public key material")
	ErrPinRequiresAlgorithm    = errors.New("keypinning: pin requires a supported algorithm")
)

func computeFingerprint(publicKeyPEM string) [32]byte {
	return sha256.Sum256([]byte(publicKeyPEM))
}

// newValidatedPin constructs and validates a PinnedKey, computing its
// fingerprint from the supplied material -- callers never supply their own
// fingerprint, precisely so a caller cannot pin one key's material under a
// fingerprint claiming to match different bytes.
func newValidatedPin(keyID protocol.SigningKeyID, algorithm Algorithm, publicKeyPEM string, provenance string, pinnedAt time.Time) (PinnedKey, error) {
	if keyID.IsZero() {
		return PinnedKey{}, ErrPinRequiresSigningKeyID
	}
	if publicKeyPEM == "" {
		return PinnedKey{}, ErrPinRequiresPublicKey
	}
	if !algorithm.Supported() {
		return PinnedKey{}, fmt.Errorf("%w: %q", ErrPinRequiresAlgorithm, algorithm)
	}
	if _, err := ParsePEMPublicKey([]byte(publicKeyPEM)); err != nil {
		return PinnedKey{}, err
	}
	return PinnedKey{
		SigningKeyID: keyID,
		Algorithm:    algorithm,
		PublicKeyPEM: publicKeyPEM,
		Fingerprint:  computeFingerprint(publicKeyPEM),
		PinnedAt:     pinnedAt,
		Provenance:   provenance,
	}, nil
}

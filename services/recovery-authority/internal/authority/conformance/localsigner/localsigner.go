// Package localsigner provides a test-only asymmetric signer/verifier pair
// for exercising the COMMITTED writer-signature boundary
// (rotationcommit.Signer / recovery.CommittedSignatureVerifier) end to end
// without KMS or any GCP dependency. It uses the standard library's
// crypto/ed25519 -- a deliberately unremarkable choice, not a production
// signing-algorithm decision: the real provider adapter (not built here)
// may use Cloud KMS asymmetric signing with a different algorithm, and
// nothing in this package or its callers assumes otherwise.
//
// Signer and Verifier are two separate types over two separate key values
// (a private key and its corresponding public key) so that emulator tests
// mirror the production boundary exactly: harness code wiring
// rotationcommit must hold only a Signer, harness code wiring recovery must
// hold only a Verifier, and neither type exposes the other's key material.
//
// Each KeyPair carries a SigningKeyID (ADR-045) derived deterministically
// from its own public key material -- a test-only stand-in for a real
// provider's immutable key-version identifier (e.g. a Cloud KMS
// CryptoKeyVersion resource name). It is not a production key-identifier
// scheme; it exists only so emulator-tier tests can exercise ActiveKeyID,
// key confirmation, key-authorization, and cross-key-mismatch behavior
// against two or more distinct, distinguishable test keys.
package localsigner

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// KeyPair holds both halves of a freshly generated test keypair. Test setup
// generates one KeyPair and then hands out Signer() to rotationcommit-side
// harness code and Verifier() to recovery-side harness code -- never the
// same value to both.
type KeyPair struct {
	public  ed25519.PublicKey
	private ed25519.PrivateKey
	keyID   protocol.SigningKeyID
}

// GenerateKeyPair creates a fresh, random keypair. Keys are generated only
// for the lifetime of a test process; nothing here persists a key.
func GenerateKeyPair() (KeyPair, error) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return KeyPair{}, fmt.Errorf("generate ed25519 keypair: %w", err)
	}
	return newKeyPair(public, private)
}

func newKeyPair(public ed25519.PublicKey, private ed25519.PrivateKey) (KeyPair, error) {
	keyID, err := keyIDForPublicKey(public)
	if err != nil {
		return KeyPair{}, err
	}
	return KeyPair{public: public, private: private, keyID: keyID}, nil
}

// keyIDForPublicKey derives a deterministic, test-only SigningKeyID from
// public key material -- two KeyPair values built from the same underlying
// key (e.g. via PrivateKeyBytes/PublicKeyBytes across a process boundary)
// always report the same SigningKeyID, exactly as a real provider's
// immutable per-version identifier would remain the same regardless of
// which process retrieved it.
func keyIDForPublicKey(public ed25519.PublicKey) (protocol.SigningKeyID, error) {
	sum := sha256.Sum256(public)
	return protocol.NewSigningKeyID("localsigner-test-key/" + hex.EncodeToString(sum[:]))
}

func (k KeyPair) Signer() Signer     { return Signer{private: k.private, keyID: k.keyID} }
func (k KeyPair) Verifier() Verifier { return Verifier{public: k.public, keyID: k.keyID} }

// KeyID returns this keypair's deterministic, test-only SigningKeyID.
func (k KeyPair) KeyID() protocol.SigningKeyID { return k.keyID }

// PrivateKeyBytes and PublicKeyBytes exist only so a keypair generated in
// one OS process (the test harness parent) can be handed, via an
// environment variable, to a helper subprocess spawned for the
// process-kill matrix (T7/T8/T10) -- the two processes must sign and
// verify with the SAME key, and Go values cannot cross a process boundary
// any other way.
func (k KeyPair) PrivateKeyBytes() []byte { return append([]byte(nil), k.private...) }
func (k KeyPair) PublicKeyBytes() []byte  { return append([]byte(nil), k.public...) }

func SignerFromPrivateKeyBytes(raw []byte) (Signer, error) {
	if len(raw) != ed25519.PrivateKeySize {
		return Signer{}, fmt.Errorf("localsigner: private key must be %d bytes, got %d", ed25519.PrivateKeySize, len(raw))
	}
	private := ed25519.PrivateKey(raw)
	public, ok := private.Public().(ed25519.PublicKey)
	if !ok {
		return Signer{}, errors.New("localsigner: could not derive public key from private key")
	}
	keyID, err := keyIDForPublicKey(public)
	if err != nil {
		return Signer{}, err
	}
	return Signer{private: private, keyID: keyID}, nil
}

func VerifierFromPublicKeyBytes(raw []byte) (Verifier, error) {
	if len(raw) != ed25519.PublicKeySize {
		return Verifier{}, fmt.Errorf("localsigner: public key must be %d bytes, got %d", ed25519.PublicKeySize, len(raw))
	}
	public := ed25519.PublicKey(raw)
	keyID, err := keyIDForPublicKey(public)
	if err != nil {
		return Verifier{}, err
	}
	return Verifier{public: public, keyID: keyID}, nil
}

// Signer implements the shape rotationcommit.Signer requires
// (ActiveKeyID, SignCommittedDigest) structurally, without importing that
// package. It holds private key material and is handed only to
// rotationcommit-side harness wiring.
type Signer struct {
	private ed25519.PrivateKey
	keyID   protocol.SigningKeyID
}

// ActiveKeyID reports this Signer's own deterministic test key identifier.
// It performs no signing and has no side effects.
func (s Signer) ActiveKeyID(_ context.Context) (protocol.SigningKeyID, error) {
	if len(s.private) == 0 {
		return protocol.SigningKeyID{}, errors.New("localsigner: signer has no key material")
	}
	return s.keyID, nil
}

// SignCommittedDigest signs digest and reports the same key identifier
// ActiveKeyID already reported -- this test signer never signs with a key
// other than its own, so the confirmation always matches by construction;
// production adapters must derive this confirmation from the actual signing
// operation, not assume it (ADR-045 §10).
func (s Signer) SignCommittedDigest(_ context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	if len(s.private) == 0 {
		return nil, protocol.SigningKeyID{}, errors.New("localsigner: signer has no key material")
	}
	return ed25519.Sign(s.private, digest.Bytes()), s.keyID, nil
}

// Verifier implements the shape recovery.CommittedSignatureVerifier
// requires structurally, without importing that package. It holds only
// public key material and is handed only to recovery-side harness wiring
// -- it can never produce a signature.
type Verifier struct {
	public ed25519.PublicKey
	keyID  protocol.SigningKeyID
}

var (
	ErrSignatureInvalid = errors.New("localsigner: signature does not verify")

	// ErrUnknownKeyID means the verifier was asked to verify a signature
	// claiming a SigningKeyID other than its own single held key -- this
	// test verifier holds exactly one public key and cannot resolve any
	// other identifier, mirroring the fail-closed "unknown key ID" case a
	// real multi-key verifier must also implement (ADR-045 §7A).
	ErrUnknownKeyID = errors.New("localsigner: verifier does not recognize this key ID")
)

// VerifyCommittedSignature verifies signature against digest using this
// Verifier's own public key, first requiring keyID to match the key this
// Verifier actually holds -- a single-key test stand-in for the historical
// key resolution a real, multi-key production verifier performs (ADR-045
// §7C). signedAt is accepted for interface-shape conformance but unused:
// this test verifier implements no compromise-ledger policy.
func (v Verifier) VerifyCommittedSignature(
	_ context.Context,
	keyID protocol.SigningKeyID,
	_ time.Time,
	digest protocol.Digest32,
	signature []byte,
) error {
	if len(v.public) == 0 {
		return errors.New("localsigner: verifier has no key material")
	}
	if keyID != v.keyID {
		return ErrUnknownKeyID
	}
	if !ed25519.Verify(v.public, digest.Bytes(), signature) {
		return ErrSignatureInvalid
	}
	return nil
}

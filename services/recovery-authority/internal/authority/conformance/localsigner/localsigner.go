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
package localsigner

import (
	"context"
	"crypto/ed25519"
	"crypto/rand"
	"errors"
	"fmt"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// KeyPair holds both halves of a freshly generated test keypair. Test setup
// generates one KeyPair and then hands out Signer() to rotationcommit-side
// harness code and Verifier() to recovery-side harness code -- never the
// same value to both.
type KeyPair struct {
	public  ed25519.PublicKey
	private ed25519.PrivateKey
}

// GenerateKeyPair creates a fresh, random keypair. Keys are generated only
// for the lifetime of a test process; nothing here persists a key.
func GenerateKeyPair() (KeyPair, error) {
	public, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return KeyPair{}, fmt.Errorf("generate ed25519 keypair: %w", err)
	}
	return KeyPair{public: public, private: private}, nil
}

func (k KeyPair) Signer() Signer     { return Signer{private: k.private} }
func (k KeyPair) Verifier() Verifier { return Verifier{public: k.public} }

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
	return Signer{private: ed25519.PrivateKey(raw)}, nil
}

func VerifierFromPublicKeyBytes(raw []byte) (Verifier, error) {
	if len(raw) != ed25519.PublicKeySize {
		return Verifier{}, fmt.Errorf("localsigner: public key must be %d bytes, got %d", ed25519.PublicKeySize, len(raw))
	}
	return Verifier{public: ed25519.PublicKey(raw)}, nil
}

// Signer implements the shape rotationcommit.Signer requires
// (SignCommittedDigest(ctx, digest) ([]byte, error)) structurally, without
// importing that package. It holds private key material and is handed only
// to rotationcommit-side harness wiring.
type Signer struct {
	private ed25519.PrivateKey
}

func (s Signer) SignCommittedDigest(_ context.Context, digest protocol.Digest32) ([]byte, error) {
	if len(s.private) == 0 {
		return nil, errors.New("localsigner: signer has no key material")
	}
	return ed25519.Sign(s.private, digest.Bytes()), nil
}

// Verifier implements the shape recovery.CommittedSignatureVerifier
// requires (VerifyCommittedSignature(ctx, digest, signature) error)
// structurally, without importing that package. It holds only public key
// material and is handed only to recovery-side harness wiring -- it can
// never produce a signature.
type Verifier struct {
	public ed25519.PublicKey
}

var ErrSignatureInvalid = errors.New("localsigner: signature does not verify")

func (v Verifier) VerifyCommittedSignature(_ context.Context, digest protocol.Digest32, signature []byte) error {
	if len(v.public) == 0 {
		return errors.New("localsigner: verifier has no key material")
	}
	if !ed25519.Verify(v.public, digest.Bytes(), signature) {
		return ErrSignatureInvalid
	}
	return nil
}

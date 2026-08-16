// Package keypinning implements ADR-045 §7C's mandatory public-key pinning
// mechanism: durable, integrity-protected storage of the public verification
// material for every approved Cloud KMS signing key version, captured while
// the version is still ENABLED, so that historical COMMITTED signature
// verification never depends on live Cloud KMS availability (ADR-045 §7).
//
// Critical invariant this package exists to enforce structurally, not just
// by convention: PinnedPublicKeyExists != KeyAuthorized. This package
// answers only "what public material corresponds to this SigningKeyID,"
// never "is this SigningKeyID allowed to represent the Recovery Authority."
// The latter question is ExpectedBinding.ApprovedSigningLineage's job
// (recovery package, ADR-045 §7A) -- this package has no opinion on it and
// never substitutes for it.
//
// This package has NO signing capability: it never imports the AsymmetricSign
// boundary (kmssigner) and pins only already-public verification material,
// never private key material. See boundary_test.go.
package keypinning

import (
	"crypto"
	"crypto/ecdsa"
	"crypto/rsa"
	"crypto/x509"
	"encoding/pem"
	"errors"
	"fmt"
)

// Algorithm identifies a supported Cloud KMS asymmetric-sign algorithm.
// Only SHA-256-digest algorithms are supported, because
// protocol.HashCanonical (and therefore every digest this Recovery
// Authority ever signs) always produces a SHA-256 Digest32 -- an algorithm
// requiring a different digest size or a raw-data signing mode (e.g.
// EC_SIGN_ED25519, EC_SIGN_P384_SHA384, RSA_SIGN_RAW_*) is structurally
// incompatible with this protocol and is deliberately not supported here,
// not merely unimplemented.
type Algorithm string

const (
	AlgorithmECSignP256SHA256        Algorithm = "EC_SIGN_P256_SHA256"
	AlgorithmECSignSecp256k1SHA256   Algorithm = "EC_SIGN_SECP256K1_SHA256"
	AlgorithmRSASignPSS2048SHA256    Algorithm = "RSA_SIGN_PSS_2048_SHA256"
	AlgorithmRSASignPSS3072SHA256    Algorithm = "RSA_SIGN_PSS_3072_SHA256"
	AlgorithmRSASignPSS4096SHA256    Algorithm = "RSA_SIGN_PSS_4096_SHA256"
	AlgorithmRSASignPKCS1_2048SHA256 Algorithm = "RSA_SIGN_PKCS1_2048_SHA256"
	AlgorithmRSASignPKCS1_3072SHA256 Algorithm = "RSA_SIGN_PKCS1_3072_SHA256"
	AlgorithmRSASignPKCS1_4096SHA256 Algorithm = "RSA_SIGN_PKCS1_4096_SHA256"
)

var ErrUnsupportedAlgorithm = errors.New("keypinning: unsupported algorithm")

// Supported reports whether a is one of the SHA-256-digest algorithms this
// Recovery Authority protocol can use.
func (a Algorithm) Supported() bool {
	switch a {
	case AlgorithmECSignP256SHA256, AlgorithmECSignSecp256k1SHA256,
		AlgorithmRSASignPSS2048SHA256, AlgorithmRSASignPSS3072SHA256, AlgorithmRSASignPSS4096SHA256,
		AlgorithmRSASignPKCS1_2048SHA256, AlgorithmRSASignPKCS1_3072SHA256, AlgorithmRSASignPKCS1_4096SHA256:
		return true
	default:
		return false
	}
}

// ErrSignatureInvalid means a signature failed cryptographic verification
// against the given public key and digest.
var ErrSignatureInvalid = errors.New("keypinning: signature does not verify")

// VerifyDigestSignature cryptographically verifies signature over digest
// (already a SHA-256 hash -- never re-hashed here) using pub, dispatching on
// a. It never trusts pub's type implicitly: a mismatch between a and pub's
// concrete Go type is a hard error, not a silent skip.
func (a Algorithm) VerifyDigestSignature(pub crypto.PublicKey, digest []byte, signature []byte) error {
	switch a {
	case AlgorithmECSignP256SHA256, AlgorithmECSignSecp256k1SHA256:
		ecKey, ok := pub.(*ecdsa.PublicKey)
		if !ok {
			return fmt.Errorf("%w: algorithm %s requires an ECDSA public key, got %T", ErrUnsupportedAlgorithm, a, pub)
		}
		if !ecdsa.VerifyASN1(ecKey, digest, signature) {
			return ErrSignatureInvalid
		}
		return nil
	case AlgorithmRSASignPSS2048SHA256, AlgorithmRSASignPSS3072SHA256, AlgorithmRSASignPSS4096SHA256:
		rsaKey, ok := pub.(*rsa.PublicKey)
		if !ok {
			return fmt.Errorf("%w: algorithm %s requires an RSA public key, got %T", ErrUnsupportedAlgorithm, a, pub)
		}
		if err := rsa.VerifyPSS(rsaKey, crypto.SHA256, digest, signature, &rsa.PSSOptions{
			SaltLength: rsa.PSSSaltLengthEqualsHash,
			Hash:       crypto.SHA256,
		}); err != nil {
			return fmt.Errorf("%w: %v", ErrSignatureInvalid, err)
		}
		return nil
	case AlgorithmRSASignPKCS1_2048SHA256, AlgorithmRSASignPKCS1_3072SHA256, AlgorithmRSASignPKCS1_4096SHA256:
		rsaKey, ok := pub.(*rsa.PublicKey)
		if !ok {
			return fmt.Errorf("%w: algorithm %s requires an RSA public key, got %T", ErrUnsupportedAlgorithm, a, pub)
		}
		if err := rsa.VerifyPKCS1v15(rsaKey, crypto.SHA256, digest, signature); err != nil {
			return fmt.Errorf("%w: %v", ErrSignatureInvalid, err)
		}
		return nil
	default:
		return ErrUnsupportedAlgorithm
	}
}

// ErrMalformedPublicKey means the PEM/DER public key material could not be
// parsed as a well-formed SubjectPublicKeyInfo.
var ErrMalformedPublicKey = errors.New("keypinning: malformed public key material")

// ParsePEMPublicKey parses a PEM-encoded SubjectPublicKeyInfo -- the format
// Cloud KMS's GetPublicKey returns -- into a crypto.PublicKey. It never
// interprets, and never accepts, a private-key PEM block.
func ParsePEMPublicKey(pemBytes []byte) (crypto.PublicKey, error) {
	block, _ := pem.Decode(pemBytes)
	if block == nil {
		return nil, fmt.Errorf("%w: no PEM block found", ErrMalformedPublicKey)
	}
	if block.Type != "PUBLIC KEY" {
		return nil, fmt.Errorf("%w: unexpected PEM block type %q (private key material is never accepted here)", ErrMalformedPublicKey, block.Type)
	}
	pub, err := x509.ParsePKIXPublicKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf("%w: %v", ErrMalformedPublicKey, err)
	}
	return pub, nil
}

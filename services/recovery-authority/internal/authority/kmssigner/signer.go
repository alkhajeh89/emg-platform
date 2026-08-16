package kmssigner

import (
	"context"
	"errors"
	"fmt"
	"hash/crc32"
	"regexp"

	"cloud.google.com/go/kms/apiv1/kmspb"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// cryptoKeyVersionShape matches a full Cloud KMS CryptoKeyVersion resource
// name -- the exact shape a SigningKeyID must have for the GCP-native
// realization ADR-045 §4 selects.
var cryptoKeyVersionShape = regexp.MustCompile(
	`^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+/cryptoKeyVersions/[^/]+$`,
)

var castagnoliTable = crc32.MakeTable(crc32.Castagnoli)

var (
	ErrKeyVersionResourceNameInvalid = errors.New("kmssigner: not a well-formed Cloud KMS CryptoKeyVersion resource name")
	ErrAlgorithmUnsupported          = errors.New("kmssigner: unsupported algorithm")
	ErrSignResponseIntegrity         = errors.New("kmssigner: AsymmetricSign response failed integrity verification")
	ErrEmptySignature                = errors.New("kmssigner: AsymmetricSign returned an empty signature")
)

// Signer is the production Cloud KMS realization of rotationcommit.Signer
// (ADR-045 §10) -- verified via compile-time assertion against that
// interface in signer_test.go, without this package importing rotationcommit
// itself (structural typing; no import-time coupling to Spanner code is
// needed or created).
//
// Signer is configured, once at construction, with EXACTLY ONE
// CryptoKeyVersion resource name -- caller-side configuration, matching
// ADR-045 §6's correction that Cloud KMS never auto-selects an active
// signing version for asymmetric operations. There is no discovery, no
// "primary version" lookup, and no fallback: ActiveKeyID always returns the
// same configured identifier for this Signer instance's entire lifetime.
// Key rotation is performed by deploying a new Signer configured with a
// new CryptoKeyVersion, never by mutating an existing Signer -- this makes
// the "ActiveKeyID selected before digest construction" race ADR-045 §10
// defends against structurally impossible within a single Signer instance,
// since both ActiveKeyID and SignCommittedDigest reference the same
// immutable configuration.
type Signer struct {
	client     AsymmetricSignClient
	keyVersion string
	keyID      protocol.SigningKeyID
	algorithm  keypinning.Algorithm
}

// New validates keyVersionResourceName and algorithm once, at construction,
// and fails closed on any mismatch -- there is no lazy/deferred validation
// path that could let a misconfigured Signer be used before its
// configuration is known-good.
func New(client AsymmetricSignClient, keyVersionResourceName string, algorithm keypinning.Algorithm) (*Signer, error) {
	if client == nil {
		return nil, errors.New("kmssigner: client is required")
	}
	if !cryptoKeyVersionShape.MatchString(keyVersionResourceName) {
		return nil, fmt.Errorf("%w: %q", ErrKeyVersionResourceNameInvalid, keyVersionResourceName)
	}
	if !algorithm.Supported() {
		return nil, fmt.Errorf("%w: %q", ErrAlgorithmUnsupported, algorithm)
	}
	keyID, err := protocol.NewSigningKeyID(keyVersionResourceName)
	if err != nil {
		return nil, fmt.Errorf("kmssigner: %w", err)
	}
	return &Signer{
		client:     client,
		keyVersion: keyVersionResourceName,
		keyID:      keyID,
		algorithm:  algorithm,
	}, nil
}

// KeyVersion returns this Signer's exactly-one configured CryptoKeyVersion
// resource name, so a caller wiring pin capture (keypinning.CaptureFromKMS)
// against the same configuration never needs to duplicate it separately.
func (s *Signer) KeyVersion() string { return s.keyVersion }

// Algorithm returns this Signer's configured algorithm, for the same
// duplication-avoidance reason as KeyVersion.
func (s *Signer) Algorithm() keypinning.Algorithm { return s.algorithm }

// ActiveKeyID always returns this Signer's one configured SigningKeyID. It
// performs no network call, discovers nothing, and cannot fail once
// construction has already validated the configuration.
func (s *Signer) ActiveKeyID(_ context.Context) (protocol.SigningKeyID, error) {
	return s.keyID, nil
}

// SignCommittedDigest signs digest (already a SHA-256 Digest32 -- never
// re-hashed here) against exactly this Signer's configured
// CryptoKeyVersion, and returns this same configured SigningKeyID as the
// confirming identifier. Because both the request's target version and the
// confirmation are the same immutable field, buildCommittedPayload's
// post-sign mismatch check (ADR-045 §10 step 7) can only ever observe a
// match for a correctly functioning Signer -- a mismatch would indicate
// this Signer's own internal state was corrupted, which the integrity
// checks below are designed to catch before ever returning a signature.
func (s *Signer) SignCommittedDigest(ctx context.Context, digest protocol.Digest32) ([]byte, protocol.SigningKeyID, error) {
	digestBytes := digest.Bytes()
	digestChecksum := int64(crc32.Checksum(digestBytes, castagnoliTable))
	response, err := s.client.AsymmetricSign(ctx, &kmspb.AsymmetricSignRequest{
		Name:         s.keyVersion,
		Digest:       &kmspb.Digest{Digest: &kmspb.Digest_Sha256{Sha256: digestBytes}},
		DigestCrc32C: wrapperspb.Int64(digestChecksum),
	})
	if err != nil {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("kmssigner: AsymmetricSign: %w", err)
	}
	// Integrity verification, per Cloud KMS's documented pattern: a false
	// VerifiedDigestCrc32C means the provider either never received our
	// checksum or could not confirm it against the digest it used --
	// either way, this response must be discarded, not trusted.
	if !response.GetVerifiedDigestCrc32C() {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: provider did not confirm the transmitted digest checksum", ErrSignResponseIntegrity)
	}
	if response.GetName() != s.keyVersion {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: response named %q, requested %q", ErrSignResponseIntegrity, response.GetName(), s.keyVersion)
	}
	signature := response.GetSignature()
	if len(signature) == 0 {
		return nil, protocol.SigningKeyID{}, ErrEmptySignature
	}
	if got := int64(crc32.Checksum(signature, castagnoliTable)); response.GetSignatureCrc32C() != nil && response.GetSignatureCrc32C().GetValue() != got {
		return nil, protocol.SigningKeyID{}, fmt.Errorf("%w: signature checksum mismatch", ErrSignResponseIntegrity)
	}
	return signature, s.keyID, nil
}

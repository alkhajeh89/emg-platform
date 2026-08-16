package recovery

import (
	"bytes"
	"context"
	"errors"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

// fakeVerifier is a TEST-ONLY, no-KMS verifier paired with a matching
// signing scheme (key + digest -> canonical hash) reproduced here
// independently of rotationcommit's own test-only signer, since test-only
// helpers are never importable across packages. It exists only to exercise
// VerifyPersistedCommitted's fail-closed behavior. It ignores keyID and
// signedAt for V1 fixtures (V1 predates SigningKeyID entirely); V2-specific
// tests supply and check a real keyID via a dedicated fake, below.
type fakeVerifier struct{ key []byte }

func fakeSignFor(key []byte, digest protocol.Digest32) []byte {
	material := append(append([]byte{}, key...), digest.Bytes()...)
	return protocol.HashCanonical(protocol.DomainCommitted, material).Bytes()
}

func (verifier fakeVerifier) VerifyCommittedSignature(_ context.Context, _ protocol.SigningKeyID, _ time.Time, digest protocol.Digest32, signature []byte) error {
	if !bytes.Equal(signature, fakeSignFor(verifier.key, digest)) {
		return errors.New("signature does not match")
	}
	return nil
}

// fakeKeyedVerifier is a TEST-ONLY verifier that additionally checks the
// keyID it is asked to verify against a single key it holds -- used to
// exercise the V2-only key-authorization path (ADR-045 §7A) independently
// of cryptographic verification.
type fakeKeyedVerifier struct {
	keyID protocol.SigningKeyID
	key   []byte
}

func (verifier fakeKeyedVerifier) VerifyCommittedSignature(_ context.Context, keyID protocol.SigningKeyID, _ time.Time, digest protocol.Digest32, signature []byte) error {
	if keyID != verifier.keyID {
		return errors.New("unrecognized key ID")
	}
	if !bytes.Equal(signature, fakeSignForV2(verifier.key, digest)) {
		return errors.New("signature does not match")
	}
	return nil
}

func fakeSignForV2(key []byte, digest protocol.Digest32) []byte {
	material := append(append([]byte{}, key...), digest.Bytes()...)
	return protocol.HashCanonical(protocol.DomainCommittedV2, material).Bytes()
}

func testBinding(t *testing.T) (ExpectedBinding, protocol.EnvironmentID, protocol.AuthorityEpoch, protocol.ResourceIncarnationID, protocol.OperationID, protocol.RevisionNumber, protocol.Digest32) {
	t.Helper()
	environment, _ := protocol.NewEnvironmentID("staging")
	epoch, _ := protocol.NewAuthorityEpoch("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1")
	resource, _ := protocol.NewResourceIncarnationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a2")
	operation, _ := protocol.NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3")
	predecessorRevision := protocol.NewRevisionNumber(8)
	predecessorDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{1}, 32))
	return ExpectedBinding{
		EnvironmentID:       environment,
		AuthorityEpoch:      epoch,
		ResourceIncarnation: resource,
		OperationID:         operation,
		PredecessorRevision: predecessorRevision,
		PredecessorDigest:   predecessorDigest,
	}, environment, epoch, resource, operation, predecessorRevision, predecessorDigest
}

func genuinePayload(t *testing.T, key []byte) protocol.CommittedPayload {
	t.Helper()
	_, environment, epoch, resource, operation, predecessorRevision, predecessorDigest := testBinding(t)
	stateDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{2}, 32))
	unsigned := protocol.NewCommittedPayload(
		environment, epoch, resource, operation,
		protocol.NewRevisionNumber(9), predecessorRevision, predecessorDigest, stateDigest,
		time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC),
		nil,
	)
	digest, err := unsigned.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	return unsigned.WithSignature(fakeSignFor(key, digest))
}

func TestVerifyPersistedCommittedAcceptsGenuinePayload(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	expected, _, _, _, _, _, _ := testBinding(t)
	payload := genuinePayload(t, key)

	if err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, payload, expected); err != nil {
		t.Fatalf("genuine payload rejected: %v", err)
	}
}

func TestVerifyPersistedCommittedRejectsAbsentSignature(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	expected, environment, epoch, resource, operation, predecessorRevision, predecessorDigest := testBinding(t)
	stateDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{2}, 32))
	unsigned := protocol.NewCommittedPayload(
		environment, epoch, resource, operation,
		protocol.NewRevisionNumber(9), predecessorRevision, predecessorDigest, stateDigest,
		time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC),
		nil,
	)
	err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, unsigned, expected)
	if !errors.Is(err, ErrCommittedSignatureMissing) {
		t.Fatalf("err = %v, want ErrCommittedSignatureMissing", err)
	}
}

func TestVerifyPersistedCommittedRejectsFabricatedSignature(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	expected, _, _, _, _, _, _ := testBinding(t)
	payload := genuinePayload(t, key)

	// Simulate a fabrication attempt: whoever produced this signature does
	// not hold the writer's key.
	fabricated := payload.WithSignature([]byte("attacker-guessed-bytes-not-a-real-signature"))
	err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, fabricated, expected)
	if !errors.Is(err, ErrCommittedSignatureInvalid) {
		t.Fatalf("err = %v, want ErrCommittedSignatureInvalid", err)
	}
}

func TestVerifyPersistedCommittedRejectsWrongSigningKey(t *testing.T) {
	t.Parallel()
	expected, _, _, _, _, _, _ := testBinding(t)
	// Signed by a DIFFERENT key than the verifier trusts -- models a
	// signature that is cryptographically well-formed but not from the
	// legitimate writer identity.
	payload := genuinePayload(t, []byte("attacker-key"))
	err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: []byte("writer-key")}, payload, expected)
	if !errors.Is(err, ErrCommittedSignatureInvalid) {
		t.Fatalf("err = %v, want ErrCommittedSignatureInvalid", err)
	}
}

func TestVerifyPersistedCommittedRejectsTamperedContentEvenWithOriginalSignature(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	expected, environment, epoch, resource, operation, predecessorRevision, predecessorDigest := testBinding(t)
	genuine := genuinePayload(t, key)

	// Take the genuine, validly-signed payload but alter its state digest --
	// the signature was computed over the ORIGINAL canonical digest, which
	// includes state_digest, so this must invalidate it even though the
	// signature bytes themselves are untouched and genuinely came from the
	// real key.
	tamperedStateDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{9}, 32))
	tampered := protocol.NewCommittedPayload(
		environment, epoch, resource, operation,
		genuine.RevisionNumber(), predecessorRevision, predecessorDigest, tamperedStateDigest,
		genuine.CommitTimestamp(),
		genuine.WriterSignature(), // reuse the ORIGINAL, genuine signature bytes
	)
	err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, tampered, expected)
	if !errors.Is(err, ErrCommittedSignatureInvalid) {
		t.Fatalf("err = %v, want ErrCommittedSignatureInvalid", err)
	}
}

func TestVerifyPersistedCommittedRejectsBindingMismatch(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	payload := genuinePayload(t, key)

	wrongOperation, _ := protocol.NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a9")
	expected, environment, epoch, resource, _, predecessorRevision, predecessorDigest := testBinding(t)
	_ = environment
	_ = epoch
	_ = resource
	_ = predecessorRevision
	_ = predecessorDigest
	expected.OperationID = wrongOperation

	err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, payload, expected)
	if !errors.Is(err, ErrCommittedBindingMismatch) {
		t.Fatalf("err = %v, want ErrCommittedBindingMismatch", err)
	}
}

// TestVerifyPersistedCommittedNeverConsultsAnExternalReadOfCurrentState is a
// documentation-and-signature test: VerifyPersistedCommitted's signature
// takes only a payload value and an expected binding -- it has no
// parameter through which a "current Spanner state" or any other later
// read could be supplied, so there is nothing for it to consult even if a
// caller wanted it to.
func TestVerifyPersistedCommittedNeverConsultsAnExternalReadOfCurrentState(t *testing.T) {
	t.Parallel()
	// This test exists to be a durable, compiled assertion that the
	// function signature has exactly (ctx, verifier, payload, expected) --
	// four parameters, none of which is a live Spanner client or database
	// handle. If a future change added such a parameter, this call site
	// would need to change, making the regression visible in review.
	key := []byte("writer-key")
	expected, _, _, _, _, _, _ := testBinding(t)
	payload := genuinePayload(t, key)
	if err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, payload, expected); err != nil {
		t.Fatal(err)
	}
}

// --- ADR-045 V2 key-authorization / trust-anchor tests -------------------

func genuinePayloadV2(t *testing.T, key []byte, keyID protocol.SigningKeyID) protocol.CommittedPayload {
	t.Helper()
	_, environment, epoch, resource, operation, predecessorRevision, predecessorDigest := testBinding(t)
	stateDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{2}, 32))
	unsigned, err := protocol.NewCommittedPayloadV2(
		environment, epoch, resource, operation,
		protocol.NewRevisionNumber(9), predecessorRevision, predecessorDigest, stateDigest,
		time.Date(2026, 8, 17, 1, 2, 3, 0, time.UTC),
		keyID,
		nil,
	)
	if err != nil {
		t.Fatal(err)
	}
	digest, err := unsigned.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	return unsigned.WithSignature(fakeSignForV2(key, digest))
}

func approvedLineageFor(approved protocol.SigningKeyID) ApprovedSigningLineage {
	return func(keyID protocol.SigningKeyID) bool { return keyID == approved }
}

func TestVerifyPersistedCommittedAcceptsGenuineV2Payload(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	keyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	expected, _, _, _, _, _, _ := testBinding(t)
	expected.ApprovedSigningLineage = approvedLineageFor(keyID)
	payload := genuinePayloadV2(t, key, keyID)

	if err := VerifyPersistedCommitted(context.Background(), fakeKeyedVerifier{keyID: keyID, key: key}, payload, expected); err != nil {
		t.Fatalf("genuine V2 payload rejected: %v", err)
	}
}

// TestVerifyPersistedCommittedRejectsAttackerOwnedKeyOutsideApprovedLineage
// is the direct regression test for the P0 this ADR-045 review found and
// corrected: a cryptographically valid signature from a real key the
// attacker fully controls must still fail if that key is not in the
// independently approved signing lineage -- content binding and
// cryptographic validity alone must never establish trust.
func TestVerifyPersistedCommittedRejectsAttackerOwnedKeyOutsideApprovedLineage(t *testing.T) {
	t.Parallel()
	approvedKeyID, err := protocol.NewSigningKeyID("projects/emg-signing/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	attackerKey := []byte("attacker-key")
	attackerKeyID, err := protocol.NewSigningKeyID("projects/attacker-project/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	expected, _, _, _, _, _, _ := testBinding(t)
	expected.ApprovedSigningLineage = approvedLineageFor(approvedKeyID)

	// The attacker signs correctly, with their own genuinely-held key --
	// cryptographic validity and content binding both hold. Only the
	// independent key-authorization check can, and must, catch this.
	payload := genuinePayloadV2(t, attackerKey, attackerKeyID)
	err = VerifyPersistedCommitted(context.Background(), fakeKeyedVerifier{keyID: attackerKeyID, key: attackerKey}, payload, expected)
	if !errors.Is(err, ErrCommittedKeyNotAuthorized) {
		t.Fatalf("err = %v, want ErrCommittedKeyNotAuthorized", err)
	}
}

func TestVerifyPersistedCommittedRejectsMissingLineageConfiguration(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	keyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	expected, _, _, _, _, _, _ := testBinding(t)
	// expected.ApprovedSigningLineage left nil deliberately.
	payload := genuinePayloadV2(t, key, keyID)

	err = VerifyPersistedCommitted(context.Background(), fakeKeyedVerifier{keyID: keyID, key: key}, payload, expected)
	if !errors.Is(err, ErrCommittedSigningLineageNotConfigured) {
		t.Fatalf("err = %v, want ErrCommittedSigningLineageNotConfigured", err)
	}
}

func TestVerifyPersistedCommittedRejectsTamperedV2KeyID(t *testing.T) {
	t.Parallel()
	key := []byte("writer-key")
	keyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	otherKeyID, err := protocol.NewSigningKeyID("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/2")
	if err != nil {
		t.Fatal(err)
	}
	expected, environment, epoch, resource, operation, predecessorRevision, predecessorDigest := testBinding(t)
	// Approve BOTH key IDs' lineage, so a lineage-check pass alone cannot
	// explain rejection -- only digest-binding tamper detection can.
	expected.ApprovedSigningLineage = func(candidate protocol.SigningKeyID) bool {
		return candidate == keyID || candidate == otherKeyID
	}
	genuine := genuinePayloadV2(t, key, keyID)

	// Take the genuine signature bytes but relabel the payload's own
	// signing_key_id to a different, also-approved key -- signing_key_id is
	// part of the signed digest, so this must invalidate the signature.
	stateDigest, _ := protocol.NewDigest32(bytes.Repeat([]byte{2}, 32))
	tampered, err := protocol.NewCommittedPayloadV2(
		environment, epoch, resource, operation,
		genuine.RevisionNumber(), predecessorRevision, predecessorDigest, stateDigest,
		genuine.CommitTimestamp(),
		otherKeyID,
		genuine.WriterSignature(),
	)
	if err != nil {
		t.Fatal(err)
	}
	err = VerifyPersistedCommitted(context.Background(), fakeKeyedVerifier{keyID: otherKeyID, key: key}, tampered, expected)
	if !errors.Is(err, ErrCommittedSignatureInvalid) {
		t.Fatalf("err = %v, want ErrCommittedSignatureInvalid", err)
	}
}

func TestVerifyPersistedCommittedV1PayloadSkipsKeyAuthorization(t *testing.T) {
	t.Parallel()
	// A V1 payload has no SigningKeyID concept at all; VerifyPersistedCommitted
	// must not require ApprovedSigningLineage for it, matching ADR-045 §11's
	// requirement that V1 fixtures remain verifiable exactly as before.
	key := []byte("writer-key")
	expected, _, _, _, _, _, _ := testBinding(t)
	// expected.ApprovedSigningLineage left nil -- must not matter for V1.
	payload := genuinePayload(t, key)
	if payload.IsV2() {
		t.Fatal("test fixture unexpectedly constructed a V2 payload")
	}
	if err := VerifyPersistedCommitted(context.Background(), fakeVerifier{key: key}, payload, expected); err != nil {
		t.Fatalf("V1 payload rejected even with no lineage configured: %v", err)
	}
}

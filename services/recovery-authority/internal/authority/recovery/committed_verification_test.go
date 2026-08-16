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
// VerifyPersistedCommitted's fail-closed behavior.
type fakeVerifier struct{ key []byte }

func fakeSignFor(key []byte, digest protocol.Digest32) []byte {
	material := append(append([]byte{}, key...), digest.Bytes()...)
	return protocol.HashCanonical(protocol.DomainCommitted, material).Bytes()
}

func (verifier fakeVerifier) VerifyCommittedSignature(_ context.Context, digest protocol.Digest32, signature []byte) error {
	if !bytes.Equal(signature, fakeSignFor(verifier.key, digest)) {
		return errors.New("signature does not match")
	}
	return nil
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

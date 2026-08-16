package protocol

import (
	"bytes"
	"testing"
	"time"
)

func testCommittedPayload(t *testing.T) CommittedPayload {
	t.Helper()
	environment, _ := NewEnvironmentID("staging")
	epoch, _ := NewAuthorityEpoch("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1")
	resource, _ := NewResourceIncarnationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a2")
	operation, _ := NewOperationID("018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a3")
	predecessorDigest, _ := NewDigest32(bytes.Repeat([]byte{1}, 32))
	stateDigest, _ := NewDigest32(bytes.Repeat([]byte{2}, 32))
	return NewCommittedPayload(
		environment, epoch, resource, operation,
		NewRevisionNumber(9), NewRevisionNumber(8),
		predecessorDigest, stateDigest,
		time.Date(2026, 8, 16, 1, 2, 3, 0, time.UTC),
		nil,
	)
}

func TestCommittedPayloadDigestExcludesSignature(t *testing.T) {
	t.Parallel()
	unsigned := testCommittedPayload(t)
	signed := unsigned.WithSignature([]byte("a-signature"))

	unsignedDigest, err := unsigned.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	signedDigest, err := signed.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if unsignedDigest.String() != signedDigest.String() {
		t.Fatal("attaching a signature must not change the canonical digest")
	}
}

func TestCommittedPayloadDigestChangesWithContent(t *testing.T) {
	t.Parallel()
	base := testCommittedPayload(t)
	baseDigest, err := base.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}

	altered := NewCommittedPayload(
		base.EnvironmentID(), base.AuthorityEpoch(), base.ResourceIncarnation(), base.OperationID(),
		NewRevisionNumber(base.RevisionNumber().Uint64()+1), // only the revision differs
		base.PredecessorRevision(), base.PredecessorDigest(), base.StateDigest(),
		base.CommitTimestamp(), nil,
	)
	alteredDigest, err := altered.CanonicalDigest()
	if err != nil {
		t.Fatal(err)
	}
	if baseDigest.String() == alteredDigest.String() {
		t.Fatal("differing revision_number must change the canonical digest")
	}
}

func TestCommittedPayloadDefensiveCopies(t *testing.T) {
	t.Parallel()
	signature := []byte("original")
	payload := testCommittedPayload(t).WithSignature(signature)
	signature[0] = 'X'
	if string(payload.WriterSignature()) != "original" {
		t.Fatal("payload retained mutable caller storage")
	}
	returned := payload.WriterSignature()
	returned[0] = 'X'
	if string(payload.WriterSignature()) != "original" {
		t.Fatal("payload exposed mutable internal storage")
	}
}

func TestCommittedPayloadNilSignatureRoundTrips(t *testing.T) {
	t.Parallel()
	payload := testCommittedPayload(t)
	if payload.WriterSignature() != nil {
		t.Fatal("unsigned payload must report a nil signature, not an empty non-nil slice")
	}
}

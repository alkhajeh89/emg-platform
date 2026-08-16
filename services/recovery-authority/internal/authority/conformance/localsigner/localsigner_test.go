package localsigner

import (
	"bytes"
	"context"
	"testing"
	"time"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

var testCommitTimestamp = time.Date(2026, 8, 17, 1, 2, 3, 0, time.UTC)

func testDigest(t *testing.T, fill byte) protocol.Digest32 {
	t.Helper()
	raw := make([]byte, 32)
	for i := range raw {
		raw[i] = fill
	}
	digest, err := protocol.NewDigest32(raw)
	if err != nil {
		t.Fatal(err)
	}
	return digest
}

func TestSignerAndVerifierAgree(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 7)
	signature, keyID, err := pair.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	if len(signature) == 0 {
		t.Fatal("expected a non-empty signature")
	}
	if keyID != pair.KeyID() {
		t.Fatalf("keyID = %q, want %q", keyID.String(), pair.KeyID().String())
	}
	if err := pair.Verifier().VerifyCommittedSignature(context.Background(), keyID, testCommitTimestamp, digest, signature); err != nil {
		t.Fatalf("genuine signature rejected: %v", err)
	}
}

func TestActiveKeyIDMatchesSignConfirmation(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	signer := pair.Signer()
	active, err := signer.ActiveKeyID(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	_, confirmed, err := signer.SignCommittedDigest(context.Background(), testDigest(t, 7))
	if err != nil {
		t.Fatal(err)
	}
	if active != confirmed {
		t.Fatalf("ActiveKeyID = %q, SignCommittedDigest confirmed %q", active.String(), confirmed.String())
	}
}

func TestKeyIDIsStableAcrossProcessBoundaryReconstruction(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	reconstructedSigner, err := SignerFromPrivateKeyBytes(pair.PrivateKeyBytes())
	if err != nil {
		t.Fatal(err)
	}
	reconstructedVerifier, err := VerifierFromPublicKeyBytes(pair.PublicKeyBytes())
	if err != nil {
		t.Fatal(err)
	}
	if reconstructedSigner.keyID != pair.KeyID() {
		t.Fatalf("reconstructed signer keyID = %q, want %q", reconstructedSigner.keyID.String(), pair.KeyID().String())
	}
	if reconstructedVerifier.keyID != pair.KeyID() {
		t.Fatalf("reconstructed verifier keyID = %q, want %q", reconstructedVerifier.keyID.String(), pair.KeyID().String())
	}
}

func TestVerifierRejectsWrongKeyPair(t *testing.T) {
	genuine, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	other, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 7)
	signature, keyID, err := genuine.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	err = other.Verifier().VerifyCommittedSignature(context.Background(), keyID, testCommitTimestamp, digest, signature)
	if err == nil {
		t.Fatal("expected verification against the wrong public key to fail")
	}
}

func TestVerifierRejectsUnknownKeyID(t *testing.T) {
	genuine, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	other, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 7)
	// Genuinely signed by genuine's own key, but the claimed keyID names a
	// DIFFERENT, otherwise-valid key -- the verifier must reject this on
	// key-identity grounds before it ever reaches cryptographic
	// verification, mirroring the fail-closed "unknown/unauthorized key ID"
	// requirement a real multi-key verifier must also implement.
	signature, _, err := genuine.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	err = genuine.Verifier().VerifyCommittedSignature(context.Background(), other.KeyID(), testCommitTimestamp, digest, signature)
	if err == nil {
		t.Fatal("expected verification claiming an unrecognized key ID to fail")
	}
}

func TestVerifierRejectsTamperedDigest(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	signature, keyID, err := pair.Signer().SignCommittedDigest(context.Background(), testDigest(t, 7))
	if err != nil {
		t.Fatal(err)
	}
	err = pair.Verifier().VerifyCommittedSignature(context.Background(), keyID, testCommitTimestamp, testDigest(t, 8), signature)
	if err == nil {
		t.Fatal("expected verification against a different digest to fail")
	}
}

func TestVerifierRejectsFabricatedSignature(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	err = pair.Verifier().VerifyCommittedSignature(context.Background(), pair.KeyID(), testCommitTimestamp, testDigest(t, 7), []byte("not-a-real-signature"))
	if err == nil {
		t.Fatal("expected a fabricated signature to fail")
	}
}

func TestSignaturesAreNotDeterministicallyGuessableAcrossKeys(t *testing.T) {
	pairA, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	pairB, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	digest := testDigest(t, 7)
	signatureA, _, err := pairA.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	signatureB, _, err := pairB.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(signatureA, signatureB) {
		t.Fatal("two different keys must not produce the same signature over the same digest")
	}
}

func TestDistinctKeyPairsHaveDistinctKeyIDs(t *testing.T) {
	pairA, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	pairB, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	if pairA.KeyID() == pairB.KeyID() {
		t.Fatal("two independently generated keypairs must not report the same SigningKeyID")
	}
}

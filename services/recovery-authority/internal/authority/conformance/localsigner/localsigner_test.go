package localsigner

import (
	"bytes"
	"context"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

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
	signature, err := pair.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	if len(signature) == 0 {
		t.Fatal("expected a non-empty signature")
	}
	if err := pair.Verifier().VerifyCommittedSignature(context.Background(), digest, signature); err != nil {
		t.Fatalf("genuine signature rejected: %v", err)
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
	signature, err := genuine.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	err = other.Verifier().VerifyCommittedSignature(context.Background(), digest, signature)
	if err == nil {
		t.Fatal("expected verification against the wrong public key to fail")
	}
}

func TestVerifierRejectsTamperedDigest(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	signature, err := pair.Signer().SignCommittedDigest(context.Background(), testDigest(t, 7))
	if err != nil {
		t.Fatal(err)
	}
	err = pair.Verifier().VerifyCommittedSignature(context.Background(), testDigest(t, 8), signature)
	if err == nil {
		t.Fatal("expected verification against a different digest to fail")
	}
}

func TestVerifierRejectsFabricatedSignature(t *testing.T) {
	pair, err := GenerateKeyPair()
	if err != nil {
		t.Fatal(err)
	}
	err = pair.Verifier().VerifyCommittedSignature(context.Background(), testDigest(t, 7), []byte("not-a-real-signature"))
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
	signatureA, err := pairA.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	signatureB, err := pairB.Signer().SignCommittedDigest(context.Background(), digest)
	if err != nil {
		t.Fatal(err)
	}
	if bytes.Equal(signatureA, signatureB) {
		t.Fatal("two different keys must not produce the same signature over the same digest")
	}
}

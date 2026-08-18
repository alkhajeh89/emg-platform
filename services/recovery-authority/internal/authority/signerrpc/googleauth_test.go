package signerrpc

import (
	"context"
	"testing"
)

func TestNewGoogleIDTokenVerifierRejectsEmptyAudience(t *testing.T) {
	if _, err := NewGoogleIDTokenVerifier("", []string{"a@example.iam.gserviceaccount.com"}); err == nil {
		t.Fatal("expected empty audience to be rejected")
	}
}

func TestNewGoogleIDTokenVerifierRejectsEmptyAllowList(t *testing.T) {
	if _, err := NewGoogleIDTokenVerifier("https://signer.example.com", nil); err == nil {
		t.Fatal("expected an empty allowed-caller list to be rejected -- there is no wildcard/any-caller mode")
	}
	if _, err := NewGoogleIDTokenVerifier("https://signer.example.com", []string{}); err == nil {
		t.Fatal("expected an empty allowed-caller list to be rejected")
	}
}

func TestNewGoogleIDTokenVerifierRejectsEmptyEmailEntry(t *testing.T) {
	if _, err := NewGoogleIDTokenVerifier("https://signer.example.com", []string{""}); err == nil {
		t.Fatal("expected an empty email entry to be rejected")
	}
}

func TestGoogleIDTokenVerifierRejectsEmptyBearerToken(t *testing.T) {
	verifier, err := NewGoogleIDTokenVerifier("https://signer.example.com", []string{"a@example.iam.gserviceaccount.com"})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := verifier.Verify(context.Background(), ""); err == nil {
		t.Fatal("expected an empty bearer token to be rejected without attempting verification")
	}
}

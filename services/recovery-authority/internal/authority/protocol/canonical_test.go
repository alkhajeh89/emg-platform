package protocol

import (
	"bytes"
	"encoding/hex"
	"errors"
	"testing"
)

func TestDeterministicCBORMapOrdering(t *testing.T) {
	t.Parallel()
	left := map[string]any{"bb": "x", "a": uint64(1)}
	right := map[string]any{"a": uint64(1), "bb": "x"}
	leftBytes, err := EncodeDeterministicCBOR(left)
	if err != nil {
		t.Fatal(err)
	}
	rightBytes, err := EncodeDeterministicCBOR(right)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(leftBytes, rightBytes) {
		t.Fatalf("deterministic encodings differ: %x != %x", leftBytes, rightBytes)
	}
	want, _ := hex.DecodeString("a26161016262626178")
	if !bytes.Equal(leftBytes, want) {
		t.Fatalf("encoding = %x, want %x", leftBytes, want)
	}
}

func TestDeterministicCBORRejectsFloatsAndUnknownTypes(t *testing.T) {
	t.Parallel()
	for _, value := range []any{1.5, struct{}{}, map[int]string{1: "x"}} {
		if _, err := EncodeDeterministicCBOR(value); !errors.Is(err, ErrUnsupportedCanonicalValue) {
			t.Fatalf("EncodeDeterministicCBOR(%T) error = %v", value, err)
		}
	}
}

func TestDomainSeparationChangesDigest(t *testing.T) {
	t.Parallel()
	encoded, err := EncodeDeterministicCBOR(map[string]any{"revision": uint64(1)})
	if err != nil {
		t.Fatal(err)
	}
	prepared := HashCanonical(DomainPrepared, encoded)
	committed := HashCanonical(DomainCommitted, encoded)
	if prepared.String() == committed.String() {
		t.Fatal("different domains produced equal digests")
	}
	if prepared.String() != HashCanonical(DomainPrepared, encoded).String() {
		t.Fatal("same domain and bytes produced a non-deterministic digest")
	}
}

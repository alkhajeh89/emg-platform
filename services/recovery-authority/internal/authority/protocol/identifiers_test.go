package protocol

import (
	"bytes"
	"errors"
	"testing"
)

const validUUIDv7 = "018f0c44-7d2b-7cc1-98c4-3dc0c8a2f7a1"

func TestEnvironmentIDValidation(t *testing.T) {
	t.Parallel()
	valid := []string{"a", "staging", "prod-01", "a1-b2"}
	for _, value := range valid {
		if _, err := NewEnvironmentID(value); err != nil {
			t.Fatalf("NewEnvironmentID(%q) returned %v", value, err)
		}
	}
	invalid := []string{"", "Staging", "1prod", "prod_01", "prod/01", string(bytes.Repeat([]byte{'a'}, 64))}
	for _, value := range invalid {
		if _, err := NewEnvironmentID(value); !errors.Is(err, ErrInvalidEnvironmentID) {
			t.Fatalf("NewEnvironmentID(%q) error = %v, want ErrInvalidEnvironmentID", value, err)
		}
	}
}

func TestUUIDv7Validation(t *testing.T) {
	t.Parallel()
	constructors := []struct {
		name string
		call func(string) error
	}{
		{"authority epoch", func(value string) error { _, err := NewAuthorityEpoch(value); return err }},
		{"operation", func(value string) error { _, err := NewOperationID(value); return err }},
		{"resource incarnation", func(value string) error { _, err := NewResourceIncarnationID(value); return err }},
	}
	for _, constructor := range constructors {
		if err := constructor.call(validUUIDv7); err != nil {
			t.Fatalf("%s rejected valid UUIDv7: %v", constructor.name, err)
		}
		for _, invalid := range []string{
			"018f0c44-7d2b-6cc1-98c4-3dc0c8a2f7a1",
			"018f0c44-7d2b-7cc1-78c4-3dc0c8a2f7a1",
			"018F0C44-7D2B-7CC1-98C4-3DC0C8A2F7A1",
			"018f0c447d2b7cc198c43dc0c8a2f7a1",
			"not-a-uuid",
		} {
			if err := constructor.call(invalid); !errors.Is(err, ErrInvalidUUIDv7) {
				t.Fatalf("%s accepted %q or returned %v", constructor.name, invalid, err)
			}
		}
	}
}

func TestRevisionCanonicalParsing(t *testing.T) {
	t.Parallel()
	for _, value := range []string{"0", "1", "18446744073709551615"} {
		parsed, err := ParseRevisionNumber(value)
		if err != nil || parsed.String() != value {
			t.Fatalf("ParseRevisionNumber(%q) = %v, %v", value, parsed, err)
		}
	}
	for _, value := range []string{"", "00", "01", "+1", "-1", "18446744073709551616"} {
		if _, err := ParseRevisionNumber(value); !errors.Is(err, ErrInvalidRevision) {
			t.Fatalf("ParseRevisionNumber(%q) error = %v, want ErrInvalidRevision", value, err)
		}
	}
}

func TestDigestUsesDefensiveCopiesAndCanonicalHex(t *testing.T) {
	t.Parallel()
	source := bytes.Repeat([]byte{0xab}, 32)
	digest, err := NewDigest32(source)
	if err != nil {
		t.Fatal(err)
	}
	source[0] = 0
	if digest.Bytes()[0] != 0xab {
		t.Fatal("digest retained mutable source storage")
	}
	returned := digest.Bytes()
	returned[0] = 0
	if digest.Bytes()[0] != 0xab {
		t.Fatal("digest exposed mutable internal storage")
	}
	parsed, err := ParseDigest32(digest.String())
	if err != nil || parsed.String() != digest.String() {
		t.Fatalf("digest round trip failed: %v", err)
	}
	if _, err := ParseDigest32("AB" + digest.String()[2:]); !errors.Is(err, ErrInvalidDigest) {
		t.Fatalf("uppercase digest error = %v, want ErrInvalidDigest", err)
	}
}

package runtimeconfig

import (
	"regexp"
	"testing"
)

func TestRequireStringFailsWhenUnset(t *testing.T) {
	t.Setenv("RC_TEST_UNSET_VAR", "")
	if _, err := RequireString("RC_TEST_DEFINITELY_UNSET_VAR"); err == nil {
		t.Fatal("expected an unset variable to fail")
	}
}

func TestRequireStringFailsWhenEmpty(t *testing.T) {
	t.Setenv("RC_TEST_EMPTY", "")
	if _, err := RequireString("RC_TEST_EMPTY"); err == nil {
		t.Fatal("expected an empty variable to fail")
	}
}

func TestRequireStringSucceeds(t *testing.T) {
	t.Setenv("RC_TEST_VALUE", "hello")
	got, err := RequireString("RC_TEST_VALUE")
	if err != nil {
		t.Fatal(err)
	}
	if got != "hello" {
		t.Fatalf("got %q, want %q", got, "hello")
	}
}

func TestRequireStringMatchingRejectsWrongShape(t *testing.T) {
	t.Setenv("RC_TEST_PATTERN", "not-a-match")
	if _, err := RequireStringMatching("RC_TEST_PATTERN", regexp.MustCompile(`^[0-9]+$`), "number"); err == nil {
		t.Fatal("expected a non-matching value to fail")
	}
}

func TestRequireStringListRejectsEmptyEntries(t *testing.T) {
	t.Setenv("RC_TEST_LIST", "a,,b")
	if _, err := RequireStringList("RC_TEST_LIST"); err == nil {
		t.Fatal("expected an empty list entry to fail")
	}
}

func TestRequireStringListTrimsAndSplits(t *testing.T) {
	t.Setenv("RC_TEST_LIST", "a@example.com, b@example.com")
	got, err := RequireStringList("RC_TEST_LIST")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0] != "a@example.com" || got[1] != "b@example.com" {
		t.Fatalf("got %v", got)
	}
}

func TestOptionalBoolDefaultsWhenUnset(t *testing.T) {
	got, err := OptionalBool("RC_TEST_DEFINITELY_UNSET_BOOL", false)
	if err != nil {
		t.Fatal(err)
	}
	if got != false {
		t.Fatal("expected default value false")
	}
}

func TestOptionalBoolParsesTrue(t *testing.T) {
	t.Setenv("RC_TEST_BOOL", "true")
	got, err := OptionalBool("RC_TEST_BOOL", false)
	if err != nil {
		t.Fatal(err)
	}
	if !got {
		t.Fatal("expected true")
	}
}

func TestOptionalBoolRejectsGarbage(t *testing.T) {
	t.Setenv("RC_TEST_BOOL_BAD", "maybe")
	if _, err := OptionalBool("RC_TEST_BOOL_BAD", false); err == nil {
		t.Fatal("expected a non-boolean value to fail rather than silently default")
	}
}

func TestSpannerDatabasePattern(t *testing.T) {
	if !SpannerDatabasePattern.MatchString("projects/p/instances/i/databases/d") {
		t.Fatal("expected well-formed database name to match")
	}
	if SpannerDatabasePattern.MatchString("localhost:9010") {
		t.Fatal("expected an emulator-shaped endpoint to NOT match the database resource-name pattern")
	}
}

func TestCryptoKeyVersionAndCryptoKeyPatterns(t *testing.T) {
	version := "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1"
	key := "projects/p/locations/l/keyRings/r/cryptoKeys/k"
	if !CryptoKeyVersionPattern.MatchString(version) {
		t.Fatal("expected well-formed CryptoKeyVersion to match")
	}
	if CryptoKeyVersionPattern.MatchString(key) {
		t.Fatal("expected a CryptoKey (no version) to NOT match the CryptoKeyVersion pattern")
	}
	if !CryptoKeyPattern.MatchString(key) {
		t.Fatal("expected well-formed CryptoKey to match")
	}
	if CryptoKeyPattern.MatchString(version) {
		t.Fatal("expected a CryptoKeyVersion to NOT match the CryptoKey (no version) pattern")
	}
}

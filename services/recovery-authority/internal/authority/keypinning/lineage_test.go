package keypinning

import "testing"

func TestCryptoKeyLineageAcceptsKeyUnderApprovedKey(t *testing.T) {
	lineage, err := CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/my-key")
	if err != nil {
		t.Fatal(err)
	}
	keyID := testSigningKeyID(t, "1")
	// testSigningKeyID uses cryptoKeys/k, not my-key -- build one under my-key.
	approvedKeyID, err := keyIDFor(t, "projects/p/locations/l/keyRings/r/cryptoKeys/my-key/cryptoKeyVersions/7")
	if err != nil {
		t.Fatal(err)
	}
	if lineage(keyID) {
		t.Fatal("key under a different CryptoKey must not be approved")
	}
	if !lineage(approvedKeyID) {
		t.Fatal("key under the approved CryptoKey must be approved")
	}
}

// TestCryptoKeyLineageRejectsPrefixCollision is the direct regression test
// for the string-prefix-injection hazard: a CryptoKey name that is a
// superstring of the approved name (sharing a naive string prefix) must
// never be treated as belonging to the approved lineage.
func TestCryptoKeyLineageRejectsPrefixCollision(t *testing.T) {
	lineage, err := CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/my-key")
	if err != nil {
		t.Fatal(err)
	}
	collidingKeyID, err := keyIDFor(t, "projects/p/locations/l/keyRings/r/cryptoKeys/my-key-evil/cryptoKeyVersions/1")
	if err != nil {
		t.Fatal(err)
	}
	if lineage(collidingKeyID) {
		t.Fatal("a CryptoKey name that is merely a superstring of the approved name must be rejected")
	}
}

func TestCryptoKeyLineageRejectsMalformedApprovedName(t *testing.T) {
	if _, err := CryptoKeyLineage("not-a-resource-name"); err == nil {
		t.Fatal("expected a malformed CryptoKey resource name to be rejected")
	}
	if _, err := CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1"); err == nil {
		t.Fatal("expected a CryptoKeyVersion (not CryptoKey) resource name to be rejected")
	}
}

func TestCryptoKeyLineageRejectsNonVersionShapedKeyID(t *testing.T) {
	lineage, err := CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/my-key")
	if err != nil {
		t.Fatal(err)
	}
	// Shares the approved lineage's literal string prefix but is not a
	// well-formed CryptoKeyVersion resource name at all (no version
	// segment) -- must never be approved merely for matching a prefix.
	notAVersion, err := keyIDFor(t, "projects/p/locations/l/keyRings/r/cryptoKeys/my-key")
	if err != nil {
		t.Fatal(err)
	}
	if lineage(notAVersion) {
		t.Fatal("a malformed/non-version-shaped identifier must never be approved")
	}
}

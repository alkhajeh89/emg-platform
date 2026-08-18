package main

import (
	"strings"
	"testing"

	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/keypinning"
	"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/protocol"
)

var validDigestHex = strings.Repeat("ab", 32)

func setAuthorityEnv(t *testing.T) {
	t.Helper()
	t.Setenv("RECOVERY_AUTHORITY_LISTEN_ADDR", ":8080")
	t.Setenv("RECOVERY_AUTHORITY_ENVIRONMENT_ID", "staging")
	t.Setenv("RECOVERY_AUTHORITY_SPANNER_DATABASE", "projects/p/instances/i/databases/d")
	t.Setenv("RECOVERY_AUTHORITY_WITNESS_BUCKET", "witness-bucket")
	t.Setenv("RECOVERY_AUTHORITY_SIGNER_ENDPOINT", "https://recovery-signer.example.internal")
	t.Setenv("RECOVERY_AUTHORITY_SIGNER_AUDIENCE", "https://recovery-signer.example.internal")
	t.Setenv("RECOVERY_AUTHORITY_APPROVED_SIGNING_CRYPTO_KEY", "projects/p2/locations/l/keyRings/r/cryptoKeys/k")
	t.Setenv("RECOVERY_AUTHORITY_PINNED_KEY_STORE_DIR", t.TempDir())
	t.Setenv("RECOVERY_AUTHORITY_COMPROMISE_LEDGER_FILE", t.TempDir()+"/ledger.jsonl")
	t.Setenv("RECOVERY_AUTHORITY_ALLOW_INSECURE", "")
}

func TestLoadConfigSucceedsWithCompleteValidConfig(t *testing.T) {
	setAuthorityEnv(t)
	cfg, err := loadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.environmentID != "staging" {
		t.Fatalf("environmentID = %q", cfg.environmentID)
	}
	if cfg.allowInsecure {
		t.Fatal("allowInsecure must default to false")
	}
}

// TestLoadConfigFailsOnMissingCriticalConfig is S5 Phase 7 item 1.
func TestLoadConfigFailsOnMissingCriticalConfig(t *testing.T) {
	requiredVars := []string{
		"RECOVERY_AUTHORITY_LISTEN_ADDR",
		"RECOVERY_AUTHORITY_ENVIRONMENT_ID",
		"RECOVERY_AUTHORITY_SPANNER_DATABASE",
		"RECOVERY_AUTHORITY_WITNESS_BUCKET",
		"RECOVERY_AUTHORITY_SIGNER_ENDPOINT",
		"RECOVERY_AUTHORITY_SIGNER_AUDIENCE",
		"RECOVERY_AUTHORITY_APPROVED_SIGNING_CRYPTO_KEY",
		"RECOVERY_AUTHORITY_PINNED_KEY_STORE_DIR",
		"RECOVERY_AUTHORITY_COMPROMISE_LEDGER_FILE",
	}
	for _, missing := range requiredVars {
		t.Run(missing, func(t *testing.T) {
			setAuthorityEnv(t)
			t.Setenv(missing, "")
			if _, err := loadConfig(); err == nil {
				t.Fatalf("expected startup to fail with %s unset", missing)
			}
		})
	}
}

func TestLoadConfigFailsOnMalformedEnvironmentID(t *testing.T) {
	setAuthorityEnv(t)
	t.Setenv("RECOVERY_AUTHORITY_ENVIRONMENT_ID", "Not A Valid ID!!")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected a malformed environment ID to fail startup")
	}
}

// TestLoadConfigFailsOnMalformedSpannerDatabase is Attack G / Attack J:
// an emulator-shaped or otherwise malformed database identifier must
// never pass configuration validation.
func TestLoadConfigFailsOnMalformedSpannerDatabase(t *testing.T) {
	setAuthorityEnv(t)
	t.Setenv("RECOVERY_AUTHORITY_SPANNER_DATABASE", "localhost:9010")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected an emulator-shaped Spanner endpoint to fail startup")
	}
}

func TestLoadConfigFailsOnMalformedApprovedSigningCryptoKey(t *testing.T) {
	setAuthorityEnv(t)
	t.Setenv("RECOVERY_AUTHORITY_APPROVED_SIGNING_CRYPTO_KEY", "not-a-resource-name")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected a malformed CryptoKey resource name to fail startup")
	}
	// A CryptoKeyVersion (with the version segment) must also be
	// rejected here -- the approved lineage is a CryptoKey, never a
	// specific version.
	setAuthorityEnv(t)
	t.Setenv("RECOVERY_AUTHORITY_APPROVED_SIGNING_CRYPTO_KEY", "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected a CryptoKeyVersion (not CryptoKey) to fail startup")
	}
}

func TestLoadConfigAllowInsecureDefaultsFalse(t *testing.T) {
	setAuthorityEnv(t)
	cfg, err := loadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.allowInsecure {
		t.Fatal("RECOVERY_AUTHORITY_ALLOW_INSECURE must default to false")
	}
}

// -- buildExpectedBinding: pure-logic tests (Attack J) --------------------

func testRuntime(t *testing.T) *runtime {
	t.Helper()
	env, err := protocol.NewEnvironmentID("staging")
	if err != nil {
		t.Fatal(err)
	}
	lineage, err := keypinning.CryptoKeyLineage("projects/p/locations/l/keyRings/r/cryptoKeys/k")
	if err != nil {
		t.Fatal(err)
	}
	return &runtime{environment: env, lineage: lineage}
}

func TestBuildExpectedBindingRejectsMalformedAuthorityEpoch(t *testing.T) {
	rt := testRuntime(t)
	_, err := rt.buildExpectedBinding(verifyRequest{
		AuthorityEpoch:      "not-a-uuid",
		ResourceIncarnation: "00000000-0000-7000-8000-000000000002",
		OperationID:         "00000000-0000-7000-8000-000000000003",
		PredecessorDigest:   "aa",
	})
	if err == nil {
		t.Fatal("expected a malformed authority_epoch to be rejected")
	}
}

func TestBuildExpectedBindingRejectsMalformedResourceIncarnation(t *testing.T) {
	rt := testRuntime(t)
	_, err := rt.buildExpectedBinding(verifyRequest{
		AuthorityEpoch:      "00000000-0000-7000-8000-000000000001",
		ResourceIncarnation: "not-a-uuid",
		OperationID:         "00000000-0000-7000-8000-000000000003",
		PredecessorDigest:   "aa",
	})
	if err == nil {
		t.Fatal("expected a malformed resource_incarnation to be rejected")
	}
}

func TestBuildExpectedBindingRejectsMalformedOperationID(t *testing.T) {
	rt := testRuntime(t)
	_, err := rt.buildExpectedBinding(verifyRequest{
		AuthorityEpoch:      "00000000-0000-7000-8000-000000000001",
		ResourceIncarnation: "00000000-0000-7000-8000-000000000002",
		OperationID:         "not-a-uuid",
		PredecessorDigest:   "aa",
	})
	if err == nil {
		t.Fatal("expected a malformed operation_id to be rejected")
	}
}

func TestBuildExpectedBindingRejectsMalformedPredecessorDigest(t *testing.T) {
	rt := testRuntime(t)
	_, err := rt.buildExpectedBinding(verifyRequest{
		AuthorityEpoch:      "00000000-0000-7000-8000-000000000001",
		ResourceIncarnation: "00000000-0000-7000-8000-000000000002",
		OperationID:         "00000000-0000-7000-8000-000000000003",
		PredecessorDigest:   "not-hex",
	})
	if err == nil {
		t.Fatal("expected a malformed predecessor_digest_hex to be rejected")
	}
}

// TestBuildExpectedBindingUsesConfiguredEnvironmentNeverRequestBody proves
// the S5 Phase 2 requirement that environment identity is never inferred
// from caller-controlled payload data: verifyRequest has no environment
// field at all, so the expected binding's EnvironmentID can only ever
// come from rt.environment (deployment configuration).
func TestBuildExpectedBindingUsesConfiguredEnvironmentNeverRequestBody(t *testing.T) {
	rt := testRuntime(t)
	expected, err := rt.buildExpectedBinding(verifyRequest{
		AuthorityEpoch:      "00000000-0000-7000-8000-000000000001",
		ResourceIncarnation: "00000000-0000-7000-8000-000000000002",
		OperationID:         "00000000-0000-7000-8000-000000000003",
		PredecessorDigest:   validDigestHex,
	})
	if err != nil {
		t.Fatal(err)
	}
	if expected.EnvironmentID != rt.environment {
		t.Fatal("expected binding's EnvironmentID must equal the deployment's configured environment")
	}
}

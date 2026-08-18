package main

import "testing"

func setSignerEnv(t *testing.T) {
	t.Helper()
	t.Setenv("RECOVERY_SIGNER_LISTEN_ADDR", ":8443")
	t.Setenv("RECOVERY_SIGNER_KEY_VERSION", "projects/p/locations/l/keyRings/r/cryptoKeys/k/cryptoKeyVersions/1")
	t.Setenv("RECOVERY_SIGNER_ALGORITHM", "EC_SIGN_P256_SHA256")
	t.Setenv("RECOVERY_SIGNER_SERVICE_AUDIENCE", "https://recovery-signer.example.internal")
	t.Setenv("RECOVERY_SIGNER_ALLOWED_CALLER_EMAILS", "authority-runtime@example.iam.gserviceaccount.com")
	t.Setenv("RECOVERY_SIGNER_ALLOW_INSECURE", "")
}

// TestLoadConfigSucceedsWithCompleteValidConfig is the baseline positive
// case every negative case below is a single-field deviation from.
func TestLoadConfigSucceedsWithCompleteValidConfig(t *testing.T) {
	setSignerEnv(t)
	cfg, err := loadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.listenAddr != ":8443" {
		t.Fatalf("listenAddr = %q", cfg.listenAddr)
	}
	if cfg.allowInsecure {
		t.Fatal("allowInsecure must default to false")
	}
}

// TestLoadConfigFailsOnMissingCriticalConfig is S5 Phase 7 item 1.
func TestLoadConfigFailsOnMissingCriticalConfig(t *testing.T) {
	requiredVars := []string{
		"RECOVERY_SIGNER_LISTEN_ADDR",
		"RECOVERY_SIGNER_KEY_VERSION",
		"RECOVERY_SIGNER_ALGORITHM",
		"RECOVERY_SIGNER_SERVICE_AUDIENCE",
		"RECOVERY_SIGNER_ALLOWED_CALLER_EMAILS",
	}
	for _, missing := range requiredVars {
		t.Run(missing, func(t *testing.T) {
			setSignerEnv(t)
			t.Setenv(missing, "")
			if _, err := loadConfig(); err == nil {
				t.Fatalf("expected startup to fail with %s unset", missing)
			}
		})
	}
}

// TestLoadConfigFailsOnMalformedSigningKeyVersion is S5 Phase 7 item 2 /
// Attack J.
func TestLoadConfigFailsOnMalformedSigningKeyVersion(t *testing.T) {
	setSignerEnv(t)
	t.Setenv("RECOVERY_SIGNER_KEY_VERSION", "not-a-resource-name")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected a malformed CryptoKeyVersion resource name to fail startup")
	}
}

func TestLoadConfigFailsOnUnsupportedAlgorithm(t *testing.T) {
	setSignerEnv(t)
	t.Setenv("RECOVERY_SIGNER_ALGORITHM", "EC_SIGN_P384_SHA384")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected an unsupported algorithm to fail startup")
	}
}

// TestLoadConfigFailsOnEmptyAllowedCallerList proves this binary cannot
// be configured with a wildcard/empty caller allow-list.
func TestLoadConfigFailsOnEmptyAllowedCallerList(t *testing.T) {
	setSignerEnv(t)
	t.Setenv("RECOVERY_SIGNER_ALLOWED_CALLER_EMAILS", "")
	if _, err := loadConfig(); err == nil {
		t.Fatal("expected an empty allowed-caller list to fail startup")
	}
}

func TestLoadConfigAllowInsecureDefaultsFalse(t *testing.T) {
	setSignerEnv(t)
	cfg, err := loadConfig()
	if err != nil {
		t.Fatal(err)
	}
	if cfg.allowInsecure {
		t.Fatal("RECOVERY_SIGNER_ALLOW_INSECURE must default to false")
	}
}

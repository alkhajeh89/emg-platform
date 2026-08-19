// Package runtimeconfig is a tiny, shared, fail-closed environment-
// variable reader used by both Recovery Authority production binaries
// (cmd/recovery-authority, cmd/recovery-signer). It never supplies a
// default value for anything security-critical: RequireString and
// RequireStringMatching return an error -- never a fallback -- when a
// variable is unset or empty, so a missing configuration value always
// prevents startup rather than silently running with an inferred or
// hardcoded value (S5 Phase 2: "malformed or missing security-critical
// values must prevent startup").
package runtimeconfig

import (
	"fmt"
	"os"
	"regexp"
	"strings"
)

// RequireString reads name from the environment and fails if it is unset
// or empty. There is no default-value parameter by design.
func RequireString(name string) (string, error) {
	value := os.Getenv(name)
	if strings.TrimSpace(value) == "" {
		return "", fmt.Errorf("runtimeconfig: required environment variable %s is unset or empty", name)
	}
	return value, nil
}

// RequireStringMatching reads name and additionally requires it match
// pattern, returning a descriptive error (never silently truncating or
// coercing) if it does not.
func RequireStringMatching(name string, pattern *regexp.Regexp, description string) (string, error) {
	value, err := RequireString(name)
	if err != nil {
		return "", err
	}
	if !pattern.MatchString(value) {
		return "", fmt.Errorf("runtimeconfig: %s=%q is not a valid %s", name, value, description)
	}
	return value, nil
}

// RequireStringList reads name as a comma-separated list, trims
// whitespace around each entry, rejects empty entries, and fails if the
// resulting list would be empty -- there is no "empty means allow
// everything" behavior anywhere that consumes this.
func RequireStringList(name string) ([]string, error) {
	raw, err := RequireString(name)
	if err != nil {
		return nil, err
	}
	var out []string
	for _, part := range strings.Split(raw, ",") {
		trimmed := strings.TrimSpace(part)
		if trimmed == "" {
			return nil, fmt.Errorf("runtimeconfig: %s contains an empty entry", name)
		}
		out = append(out, trimmed)
	}
	if len(out) == 0 {
		return nil, fmt.Errorf("runtimeconfig: %s must contain at least one entry", name)
	}
	return out, nil
}

// OptionalBool reads name as a boolean, defaulting to defaultValue only
// when the variable is entirely unset. This is deliberately restricted
// to non-security-critical toggles (e.g. an explicit, off-by-default
// "allow insecure local development transport" escape hatch) -- never
// used for a value that gates a security boundary's presence/absence by
// itself without also being logged loudly at startup.
func OptionalBool(name string, defaultValue bool) (bool, error) {
	raw, set := os.LookupEnv(name)
	if !set || strings.TrimSpace(raw) == "" {
		return defaultValue, nil
	}
	switch strings.ToLower(strings.TrimSpace(raw)) {
	case "true", "1", "yes":
		return true, nil
	case "false", "0", "no":
		return false, nil
	default:
		return false, fmt.Errorf("runtimeconfig: %s=%q is not a valid boolean", name, raw)
	}
}

// OptionalString reads name from the environment, returning defaultValue
// if it is entirely unset. Unlike RequireString, an unset value is never
// an error here -- reserved for genuinely optional, non-security-critical
// configuration where absence has a well-defined, safe meaning (e.g. an
// optional trust-anchor file path where empty means "use the platform's
// default trust store" rather than "skip verification").
func OptionalString(name string, defaultValue string) string {
	value, set := os.LookupEnv(name)
	if !set {
		return defaultValue
	}
	return value
}

// SpannerDatabasePattern matches a well-formed Cloud Spanner database
// resource name.
var SpannerDatabasePattern = regexp.MustCompile(
	`^projects/[^/]+/instances/[^/]+/databases/[^/]+$`,
)

// CryptoKeyVersionPattern matches a well-formed Cloud KMS CryptoKeyVersion
// resource name.
var CryptoKeyVersionPattern = regexp.MustCompile(
	`^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+/cryptoKeyVersions/[^/]+$`,
)

// CryptoKeyPattern matches a well-formed Cloud KMS CryptoKey resource
// name (no version segment).
var CryptoKeyPattern = regexp.MustCompile(
	`^projects/[^/]+/locations/[^/]+/keyRings/[^/]+/cryptoKeys/[^/]+$`,
)

package kmssigner_test

import (
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

// TestKMSSignerHasNoAdministrativeCapability proves, at the source level,
// that this package cannot mutate Spanner authority state, administer the
// GCS witness, administer Resource Manager/IAM/billing, or call any Cloud
// KMS key-administration/destruction/IAM method -- it imports no such
// package and calls no such method by name anywhere in its own source
// (Phase 8 boundary requirement; the default is NO key-administration
// capability at all, per ADR-045 §7B).
func TestKMSSignerHasNoAdministrativeCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/spanner":               true,
		"cloud.google.com/go/spanner/apiv1":         true,
		"cloud.google.com/go/storage":               true,
		"cloud.google.com/go/resourcemanager/apiv3": true,
		"cloud.google.com/go/billing/apiv1":         true,
	}
	forbiddenCalls := map[string]bool{
		"CreateCryptoKey":               true,
		"CreateCryptoKeyVersion":        true,
		"UpdateCryptoKey":               true,
		"UpdateCryptoKeyPrimaryVersion": true,
		"DestroyCryptoKeyVersion":       true,
		"RestoreCryptoKeyVersion":       true,
		"CreateKeyRing":                 true,
		"SetIamPolicy":                  true,
		"IAM":                           true,
		// A signing runtime has no need to retrieve public keys at all
		// (IAM permission separation: cloudkms.cryptoKeyVersions.useToSign
		// vs. .viewPublicKey) -- that capability belongs entirely to the
		// separate keypinning.PublicKeyClient boundary.
		"GetPublicKey": true,
	}

	files, err := filepath.Glob(filepath.Join(".", "*.go"))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range files {
		if strings.HasSuffix(path, "_test.go") {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		parsed, err := parser.ParseFile(token.NewFileSet(), path, data, parser.ParseComments)
		if err != nil {
			t.Fatal(err)
		}
		for _, imported := range parsed.Imports {
			name, unquoteErr := strconv.Unquote(imported.Path.Value)
			if unquoteErr != nil {
				t.Fatal(unquoteErr)
			}
			if forbiddenImports[name] {
				t.Errorf("forbidden import %q in %s", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if forbiddenCalls[sel.Sel.Name] {
				t.Errorf("forbidden call/reference to %q in %s -- the signer runtime must have no key-administration or public-key-retrieval capability", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestKMSSignerNeverHandlesPrivateKeyMaterial proves no source file in this
// package references Go's private-key types or a "PRIVATE KEY" PEM literal
// -- private key material never leaves Cloud KMS's boundary (ADR-045 §5).
func TestKMSSignerNeverHandlesPrivateKeyMaterial(t *testing.T) {
	t.Parallel()
	forbiddenSubstrings := []string{
		"PRIVATE KEY",
		"rsa.PrivateKey",
		"ecdsa.PrivateKey",
		"ed25519.PrivateKey",
	}
	files, err := filepath.Glob(filepath.Join(".", "*.go"))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range files {
		if strings.HasSuffix(path, "_test.go") {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatal(err)
		}
		content := string(data)
		for _, forbidden := range forbiddenSubstrings {
			if strings.Contains(content, forbidden) {
				t.Errorf("%s contains forbidden private-key reference %q", path, forbidden)
			}
		}
	}
}

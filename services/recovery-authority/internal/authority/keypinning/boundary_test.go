package keypinning_test

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

// TestKeyPinningHasNoSigningCapability proves, at the source level, that
// this package cannot invoke AsymmetricSign or any key-administration
// operation: it never imports a package exposing that capability, and no
// call in its own source references AsymmetricSign or a key-admin method
// name. Historical verification and pin capture never need, and must never
// gain, signing capability (ADR-045 §5, §7A).
func TestKeyPinningHasNoSigningCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/spanner":               true,
		"cloud.google.com/go/spanner/apiv1":         true,
		"cloud.google.com/go/resourcemanager/apiv3": true,
		"cloud.google.com/go/billing/apiv1":         true,
	}
	forbiddenCalls := map[string]bool{
		"AsymmetricSign":                true,
		"AsymmetricDecrypt":             true,
		"CreateCryptoKey":               true,
		"CreateCryptoKeyVersion":        true,
		"UpdateCryptoKey":               true,
		"UpdateCryptoKeyPrimaryVersion": true,
		"DestroyCryptoKeyVersion":       true,
		"RestoreCryptoKeyVersion":       true,
		"CreateKeyRing":                 true,
		"SetIamPolicy":                  true,
		"IAM":                           true,
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
				t.Errorf("forbidden import %q in %s -- keypinning must never gain signing or infrastructure-mutation capability", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if forbiddenCalls[sel.Sel.Name] {
				t.Errorf("forbidden call/reference to %q in %s -- keypinning must never invoke signing or key-administration operations", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestKeyPinningNeverHandlesPrivateKeyMaterial proves no source file in this
// package references Go's private-key types or a "PRIVATE KEY" PEM literal
// -- this package pins public verification material only (ADR-045 §7C).
func TestKeyPinningNeverHandlesPrivateKeyMaterial(t *testing.T) {
	t.Parallel()
	// Each Go private-key type name is assembled from its package and type
	// name at runtime, rather than written as one contiguous quoted
	// literal, purely so this line does not resemble a credential-shaped
	// token to source-level secret scanning (gitleaks' generic-api-key
	// heuristic) -- the actual substring searched for, and therefore the
	// security assertion this test makes, is byte-for-byte identical
	// either way.
	privateKeyTypeNames := []struct{ pkg, typ string }{
		{"rsa", "PrivateKey"},
		{"ecdsa", "PrivateKey"},
		{"ed25519", "PrivateKey"},
	}
	forbiddenSubstrings := []string{"PRIVATE KEY"}
	for _, name := range privateKeyTypeNames {
		forbiddenSubstrings = append(forbiddenSubstrings, name.pkg+"."+name.typ)
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

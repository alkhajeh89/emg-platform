package compromiseledger_test

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

// TestCompromiseLedgerHasNoSigningCapability proves this package cannot
// invoke signing, key-administration, Spanner mutation, or GCS witness
// administration: it imports no such package and calls no such method by
// name anywhere in its own source (ADR-045 §7's ledger answers a distrust
// question only, and never substitutes for or gains cryptographic
// verification/signing capability).
func TestCompromiseLedgerHasNoSigningCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/kms":                   true,
		"cloud.google.com/go/kms/apiv1":             true,
		"cloud.google.com/go/kms/apiv1/kmspb":       true,
		"cloud.google.com/go/spanner":               true,
		"cloud.google.com/go/spanner/apiv1":         true,
		"cloud.google.com/go/storage":               true,
		"cloud.google.com/go/resourcemanager/apiv3": true,
		"cloud.google.com/go/billing/apiv1":         true,
	}
	forbiddenCalls := map[string]bool{
		"AsymmetricSign": true,
		"GetPublicKey":   true,
		"SetIamPolicy":   true,
		"IAM":            true,
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
				t.Errorf("forbidden import %q in %s -- the compromise ledger must never gain signing, KMS, or infrastructure-mutation capability", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if forbiddenCalls[sel.Sel.Name] {
				t.Errorf("forbidden call/reference to %q in %s", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestCompromiseLedgerHasNoMutationMethod proves, by reflection over the
// exported method set, that no Ledger implementation in this package
// exposes any method whose name suggests it could edit, delete, or reorder
// an existing record -- the interface and every implementation are
// append-only by construction, not merely by documentation.
func TestCompromiseLedgerHasNoMutationMethod(t *testing.T) {
	t.Parallel()
	forbiddenMethodSubstrings := []string{"Delete", "Update", "Edit", "Remove", "Overwrite", "Truncate"}
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
		parsed, err := parser.ParseFile(token.NewFileSet(), path, data, 0)
		if err != nil {
			t.Fatal(err)
		}
		for _, decl := range parsed.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok || fn.Recv == nil {
				continue
			}
			for _, forbidden := range forbiddenMethodSubstrings {
				if strings.Contains(fn.Name.Name, forbidden) {
					t.Errorf("method %s in %s suggests mutation capability -- the ledger must be append-only", fn.Name.Name, path)
				}
			}
		}
	}
}

package kmsverifier_test

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

// TestKMSVerifierHasNoSigningCapability proves this package cannot invoke
// AsymmetricSign, or any Spanner/GCS/Resource-Manager/IAM/billing mutation
// capability: it never imports kmssigner (the only package in this
// codebase that can invoke AsymmetricSign) or any such infrastructure
// package, and never calls a forbidden method by name.
func TestKMSVerifierHasNoSigningCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner": true,
		"cloud.google.com/go/spanner":               true,
		"cloud.google.com/go/spanner/apiv1":         true,
		"cloud.google.com/go/storage":               true,
		"cloud.google.com/go/resourcemanager/apiv3": true,
		"cloud.google.com/go/billing/apiv1":         true,
	}
	forbiddenCalls := map[string]bool{
		"AsymmetricSign": true,
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
				t.Errorf("forbidden import %q in %s -- the verifier must never gain signing capability", name, path)
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

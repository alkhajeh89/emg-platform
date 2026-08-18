package signerrpc_test

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

// TestSignerRPCHasNoResourceMutationCapability proves this package is
// pure transport + authentication: it never imports Cloud KMS, Spanner,
// or GCS, and never calls a key-administration/Spanner-mutation/
// witness-administration method. It legitimately imports
// google.golang.org/api/idtoken (authentication only, no resource
// capability) -- that import is not restricted here.
func TestSignerRPCHasNoResourceMutationCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/kms":           true,
		"cloud.google.com/go/kms/apiv1":     true,
		"cloud.google.com/go/spanner":       true,
		"cloud.google.com/go/spanner/apiv1": true,
		"cloud.google.com/go/storage":       true,
	}
	forbiddenCalls := map[string]bool{
		"AsymmetricSign": true, "Commit": true, "CreateExactIfAbsent": true,
		"DestroyCryptoKeyVersion": true, "SetIamPolicy": true,
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
				t.Errorf("forbidden import %q in %s -- signerrpc is transport/auth only", name, path)
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

func TestSignerRPCContainsNoStaticCredential(t *testing.T) {
	t.Parallel()
	forbidden := []string{"PRIVATE KEY", "BEGIN CERTIFICATE", "AKIA", "ya29."}
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
		for _, marker := range forbidden {
			if strings.Contains(content, marker) {
				t.Errorf("%s contains forbidden credential-shaped marker %q", path, marker)
			}
		}
	}
}

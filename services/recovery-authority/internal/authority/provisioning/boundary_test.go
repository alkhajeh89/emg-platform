package provisioning_test

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

// TestProvisioningPackageMakesNoCloudCallsAtAll mirrors iam's own
// TestIAMPackageMakesNoCloudCallsAtAll: this package is pure, offline data
// -- no cloud SDK import, no network capability, no credential handling.
// It only parses and validates an embedded JSON file. S6 Phase 8 designs
// and cross-references a provisioning contract; it never applies one.
func TestProvisioningPackageMakesNoCloudCallsAtAll(t *testing.T) {
	t.Parallel()
	forbiddenImportPrefixes := []string{
		"cloud.google.com/",
		"google.golang.org/api",
		"google.golang.org/grpc",
		"github.com/googleapis/",
		"k8s.io/",
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
			for _, prefix := range forbiddenImportPrefixes {
				if strings.HasPrefix(name, prefix) {
					t.Errorf("forbidden cloud-SDK import %q in %s -- the provisioning contract package must remain pure offline data/validation", name, path)
				}
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			forbiddenCalls := map[string]bool{
				"SetIamPolicy": true, "AsymmetricSign": true, "Commit": true,
				"CreateExactIfAbsent": true, "GetPublicKey": true, "Apply": true,
			}
			if forbiddenCalls[sel.Sel.Name] {
				t.Errorf("forbidden call/reference to %q in %s -- this package never calls a live capability, only describes one", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestProvisioningPackageContainsNoStaticCredential is a source-level,
// defense-in-depth companion to gitleaks, mirroring iam's own equivalent
// test.
func TestProvisioningPackageContainsNoStaticCredential(t *testing.T) {
	t.Parallel()
	forbidden := []string{"PRIVATE KEY", "BEGIN CERTIFICATE", "AKIA", "ya29."}
	files, err := filepath.Glob(filepath.Join(".", "*"))
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range files {
		if strings.HasSuffix(path, "_test.go") {
			continue
		}
		info, statErr := os.Stat(path)
		if statErr != nil || info.IsDir() {
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

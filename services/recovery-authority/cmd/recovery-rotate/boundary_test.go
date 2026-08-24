package main

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

// TestRecoveryRotateHasNoSigningCapability mirrors
// cmd/recovery-authority's own regression test of the same shape: this
// binary must never import Cloud KMS or kmssigner, and must never
// construct a test/conformance signer -- signing is only ever reachable
// through the separately-deployed recovery-signer process, over signerrpc,
// exactly as cmd/recovery-authority already enforces.
func TestRecoveryRotateHasNoSigningCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/kms":       true,
		"cloud.google.com/go/kms/apiv1": true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner":               true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner": true,
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
				t.Errorf("forbidden import %q in %s -- recovery-rotate must never gain KMS signing capability", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			ident, ok := n.(*ast.Ident)
			if !ok {
				return true
			}
			if ident.Name == "AsymmetricSign" || ident.Name == "GenerateKeyPair" {
				t.Errorf("forbidden reference to signing construct %q in %s", ident.Name, path)
			}
			return true
		})
	}
}

// TestRecoveryRotateNeverImportsBootstrap proves this binary never invokes
// genesis -- it is exclusively the ordinary-rotation entry point.
func TestRecoveryRotateNeverImportsBootstrap(t *testing.T) {
	t.Parallel()
	forbidden := "github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/bootstrap"
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
			if name == forbidden {
				t.Errorf("forbidden import %q in %s -- recovery-rotate must never depend on bootstrap", name, path)
			}
		}
	}
}

// TestRecoveryRotateNeverSkipsTLSVerification mirrors
// cmd/recovery-authority's own TLS regression test exactly.
func TestRecoveryRotateNeverSkipsTLSVerification(t *testing.T) {
	t.Parallel()
	forbiddenIdents := map[string]bool{
		"InsecureSkipVerify":    true,
		"VerifyPeerCertificate": true,
		"VerifyConnection":      true,
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
		ast.Inspect(parsed, func(n ast.Node) bool {
			ident, ok := n.(*ast.Ident)
			if !ok {
				return true
			}
			if forbiddenIdents[ident.Name] {
				t.Errorf("forbidden reference to %q in %s -- TLS verification must never be weakened or overridden", ident.Name, path)
			}
			return true
		})
	}
}

func TestRecoveryRotateContainsNoStaticCredential(t *testing.T) {
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

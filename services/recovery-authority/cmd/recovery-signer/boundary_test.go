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

// TestRecoverySignerHasNoAuthorityWitnessCapability is the direct S5
// Phase 3 item 3 / Attack E/F regression test: this binary must never
// import Spanner or GCS witness code, and must never construct a
// test/conformance signer -- so it is structurally impossible for this
// process to mutate Spanner or the witness bucket, or to serve traffic
// from anything other than the real kmssigner.Signer.
func TestRecoverySignerHasNoAuthorityWitnessCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/spannercommit":              true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/gcswitness":                 true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit":             true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter": true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner":    true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/witness":        true,
		"cloud.google.com/go/spanner":       true,
		"cloud.google.com/go/spanner/apiv1": true,
		"cloud.google.com/go/storage":       true,
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
				t.Errorf("forbidden import %q in %s -- recovery-signer must never gain Spanner/witness capability", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			ident, ok := n.(*ast.Ident)
			if !ok {
				return true
			}
			// Attack A: a test/local signer type name must never appear
			// in this binary's production source at all.
			if ident.Name == "LocalSigner" || ident.Name == "GenerateKeyPair" {
				t.Errorf("forbidden reference to test-only signer construct %q in %s", ident.Name, path)
			}
			return true
		})
	}
}

func TestRecoverySignerContainsNoStaticCredential(t *testing.T) {
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

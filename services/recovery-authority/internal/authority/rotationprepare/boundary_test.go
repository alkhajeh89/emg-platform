package rotationprepare_test

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

// TestRotationPrepareHasNoSigningOrWitnessCapability proves, at the source
// level, that this package cannot sign anything, cannot write or administer
// the GCS witness, and cannot administer Cloud KMS, Resource Manager, IAM,
// or billing -- it imports no such package and calls no such method by name
// anywhere in its own source. This package's entire job is read-only
// pre-commit state acquisition plus deterministic mutation/CommitRequest
// construction; it must never gain a path to acceptance provenance on its
// own (ADR-044 §7).
func TestRotationPrepareHasNoSigningOrWitnessCapability(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/kms/apiv1":             true,
		"cloud.google.com/go/storage":               true,
		"cloud.google.com/go/resourcemanager/apiv3": true,
		"cloud.google.com/go/billing/apiv1":         true,
	}
	forbiddenCalls := map[string]bool{
		"AsymmetricSign":          true,
		"SignCommittedDigest":     true,
		"CreateExactIfAbsent":     true,
		"SetIamPolicy":            true,
		"CreateCryptoKeyVersion":  true,
		"DestroyCryptoKeyVersion": true,
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
				t.Errorf("forbidden call/reference to %q in %s -- rotationprepare must never gain signing or witness-write capability", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestRotationPrepareNeverInvokesCommit proves this package never calls a
// method literally named Commit -- Commit remains exclusively
// rotationcommit.CompleteRotationCommit's responsibility, on the caller's
// side of the boundary this package's own doc comment describes.
func TestRotationPrepareNeverInvokesCommit(t *testing.T) {
	t.Parallel()
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
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if sel.Sel.Name == "Commit" {
				t.Errorf("forbidden call to a method named Commit in %s -- rotationprepare must never invoke Commit itself", path)
			}
			return true
		})
	}
}

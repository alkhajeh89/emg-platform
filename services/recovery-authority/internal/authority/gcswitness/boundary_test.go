package gcswitness

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

// nonTestGoFiles returns every non-test .go file in this package directory.
func nonTestGoFiles(t *testing.T) []string {
	t.Helper()
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, f := range files {
		if !strings.HasSuffix(f, "_test.go") {
			out = append(out, f)
		}
	}
	return out
}

// TestNoGRPCClientConstruction proves the package never calls
// storage.NewGRPCClient (the qualification explicitly requires the
// HTTP/JSON transport, never gRPC).
func TestNoGRPCClientConstruction(t *testing.T) {
	t.Parallel()
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if sel.Sel.Name == "NewGRPCClient" {
				t.Errorf("forbidden storage.NewGRPCClient reference in %s", path)
			}
			return true
		})
	}
}

// TestNoForbiddenStorageMethods proves the package never calls any
// mutation/authority-broadening method on a *storage.ObjectHandle or
// *storage.BucketHandle: Delete, Update, ComposeFrom, CopyTo, ACL, IAM,
// Retention/Lifecycle mutation. This is a name-based AST scan over method
// selectors in this package's own (non-test) source, which is exactly the
// surface under our control.
func TestNoForbiddenStorageMethods(t *testing.T) {
	t.Parallel()
	forbidden := map[string]bool{
		"Delete":           true,
		"Update":           true,
		"ComposeFrom":      true,
		"CopierFrom":       true,
		"CopyTo":           true,
		"ACL":              true,
		"IAM":              true,
		"Retention":        true,
		"Lifecycle":        true,
		"SetRetention":     true,
		"SetLifecycle":     true,
		"LockRetention":    true,
		"ObjectACL":        true,
		"BucketPolicyOnly": true,
	}
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			call, ok := n.(*ast.CallExpr)
			if !ok {
				return true
			}
			sel, ok := call.Fun.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if forbidden[sel.Sel.Name] {
				t.Errorf("forbidden storage method call %q in %s", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestNoResumableOrChunkedUploadConfiguration proves that wherever this
// package sets Writer.ChunkSize, it is always the literal 0 -- never a
// non-zero value that would enable resumable/chunked upload behavior.
func TestNoResumableOrChunkedUploadConfiguration(t *testing.T) {
	t.Parallel()
	found := false
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			assign, ok := n.(*ast.AssignStmt)
			if !ok {
				return true
			}
			for i, lhs := range assign.Lhs {
				sel, ok := lhs.(*ast.SelectorExpr)
				if !ok || sel.Sel.Name != "ChunkSize" {
					continue
				}
				found = true
				if i >= len(assign.Rhs) {
					continue
				}
				lit, ok := assign.Rhs[i].(*ast.BasicLit)
				if !ok || lit.Value != "0" {
					t.Errorf("ChunkSize assigned a non-zero-literal value in %s: %#v", path, assign.Rhs[i])
				}
			}
			return true
		})
	}
	if !found {
		t.Fatal("expected at least one Writer.ChunkSize assignment in this package's source")
	}
}

// TestCreatePathAlwaysUsesDoesNotExistCondition proves the only
// storage.Conditions literal constructed in this package always sets
// DoesNotExist: true, and never GenerationMatch/GenerationNotMatch to some
// other value that would weaken the create-only-if-absent guarantee.
func TestCreatePathAlwaysUsesDoesNotExistCondition(t *testing.T) {
	t.Parallel()
	found := false
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			composite, ok := n.(*ast.CompositeLit)
			if !ok {
				return true
			}
			sel, ok := composite.Type.(*ast.SelectorExpr)
			if !ok || sel.Sel.Name != "Conditions" {
				return true
			}
			found = true
			sawDoesNotExistTrue := false
			for _, elt := range composite.Elts {
				kv, ok := elt.(*ast.KeyValueExpr)
				if !ok {
					continue
				}
				key, ok := kv.Key.(*ast.Ident)
				if !ok {
					continue
				}
				switch key.Name {
				case "DoesNotExist":
					if ident, ok := kv.Value.(*ast.Ident); ok && ident.Name == "true" {
						sawDoesNotExistTrue = true
					}
				case "GenerationMatch", "GenerationNotMatch":
					t.Errorf("storage.Conditions in %s sets %s, which must never be used for the witness create path", path, key.Name)
				}
			}
			if !sawDoesNotExistTrue {
				t.Errorf("storage.Conditions literal in %s does not set DoesNotExist: true", path)
			}
			return true
		})
	}
	if !found {
		t.Fatal("expected at least one storage.Conditions literal in this package's source")
	}
}

// TestNoExportedStorageHandleEscape proves no exported function or method
// in this package returns *storage.Client, *storage.BucketHandle, or
// *storage.ObjectHandle. NewClient is the sole, documented exception: it
// exists specifically to construct the client that the caller then hands to
// New, and returning it is the only way this package can offer "use
// storage.NewClient, never storage.NewGRPCClient" as an enforceable choice
// without duplicating client-construction options wholesale. Every other
// exported identifier must not do this.
func TestNoExportedStorageHandleEscape(t *testing.T) {
	t.Parallel()
	forbiddenReturnTypes := map[string]bool{
		"BucketHandle": true,
		"ObjectHandle": true,
	}
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		for _, decl := range parsed.Decls {
			fn, ok := decl.(*ast.FuncDecl)
			if !ok || !ast.IsExported(fn.Name.Name) || fn.Type.Results == nil {
				continue
			}
			for _, field := range fn.Type.Results.List {
				name := typeName(field.Type)
				if forbiddenReturnTypes[name] {
					t.Errorf("exported func %s in %s returns forbidden storage handle type %s", fn.Name.Name, path, name)
				}
				if name == "Client" && fn.Name.Name != "NewClient" {
					t.Errorf("exported func %s in %s returns *storage.Client; only NewClient may do this", fn.Name.Name, path)
				}
			}
		}
	}
}

func typeName(expr ast.Expr) string {
	switch t := expr.(type) {
	case *ast.StarExpr:
		return typeName(t.X)
	case *ast.SelectorExpr:
		return t.Sel.Name
	case *ast.Ident:
		return t.Name
	default:
		return ""
	}
}

// TestAuthorityImportBoundary mirrors the existing rotationcommit boundary
// test: this package must never import the frozen rotationcommit internals
// or attempt to reach acceptedRotationContext/signing capability, and must
// never import "unsafe".
func TestAuthorityImportBoundary(t *testing.T) {
	t.Parallel()
	forbidden := map[string]bool{
		"unsafe": true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/rotationcommit": true,
	}
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatal(err)
		}
		for _, imported := range parsed.Imports {
			name, unquoteErr := strconv.Unquote(imported.Path.Value)
			if unquoteErr != nil {
				t.Fatal(unquoteErr)
			}
			if forbidden[name] {
				t.Errorf("forbidden import %q in %s", name, path)
			}
		}
	}
}

// TestNoListMethodUsage proves this package never calls a LIST-shaped
// method (Objects, Buckets, or anything named/prefixed List*) anywhere in
// its own non-test source. The bucket-availability fix (confirmBucketExists,
// gcswitness.go) resolves the bucket-vs-object-404 ambiguity via a single,
// exact BucketHandle.Attrs(ctx) call specifically because that is the
// narrowest possible provider call that answers "does this exact bucket
// exist" -- never LIST, which this package has always forbidden for
// correctness reasons unrelated to this fix (LIST results are eventually
// consistent and would reintroduce exactly the kind of ambiguity
// create-if-absent/exact-key reads are designed to avoid).
func TestNoListMethodUsage(t *testing.T) {
	t.Parallel()
	for _, path := range nonTestGoFiles(t) {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			sel, ok := n.(*ast.SelectorExpr)
			if !ok {
				return true
			}
			if sel.Sel.Name == "Objects" || sel.Sel.Name == "Buckets" || strings.HasPrefix(sel.Sel.Name, "List") {
				t.Errorf("forbidden LIST-shaped method reference %q in %s", sel.Sel.Name, path)
			}
			return true
		})
	}
}

// TestBucketAvailabilityClassificationNeverInspectsErrorText proves the
// bucket-vs-object-404 distinction (confirmBucketExists and its two call
// sites in Exists/ReadExact) is decided exclusively via typed error
// classification (errors.Is/errors.As against SDK sentinels), never by
// inspecting an error's human-readable message text (e.g.
// strings.Contains(err.Error(), ...)) -- provider error message wording is
// not a documented, stable API contract, and classifying on it would
// reintroduce exactly the kind of unreliable, string-dependent behavior
// the P0 fix was written to avoid.
func TestBucketAvailabilityClassificationNeverInspectsErrorText(t *testing.T) {
	t.Parallel()
	data, err := os.ReadFile("gcswitness.go")
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := parser.ParseFile(token.NewFileSet(), "gcswitness.go", data, 0)
	if err != nil {
		t.Fatal(err)
	}
	ast.Inspect(parsed, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		sel, ok := call.Fun.(*ast.SelectorExpr)
		if !ok {
			return true
		}
		if sel.Sel.Name == "Contains" || sel.Sel.Name == "HasPrefix" || sel.Sel.Name == "HasSuffix" {
			// Confirm this isn't operating on the result of err.Error() --
			// a coarse but sufficient check given this package's small size
			// and the absence of any legitimate reason to string-match an
			// error message anywhere in it.
			for _, arg := range call.Args {
				argCall, ok := arg.(*ast.CallExpr)
				if !ok {
					continue
				}
				argSel, ok := argCall.Fun.(*ast.SelectorExpr)
				if ok && argSel.Sel.Name == "Error" {
					t.Errorf("forbidden error-message string inspection (%s on the result of .Error()) in gcswitness.go", sel.Sel.Name)
				}
			}
		}
		return true
	})
}

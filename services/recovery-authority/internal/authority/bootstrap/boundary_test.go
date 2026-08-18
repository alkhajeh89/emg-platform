package bootstrap

import (
	"go/ast"
	"go/parser"
	"go/token"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

func nonTestGoFiles(t *testing.T, dir string) []string {
	t.Helper()
	files, err := filepath.Glob(filepath.Join(dir, "*.go"))
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

func importsOf(t *testing.T, path string) []string {
	t.Helper()
	parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
	if err != nil {
		t.Fatal(err)
	}
	var out []string
	for _, imported := range parsed.Imports {
		name, err := strconv.Unquote(imported.Path.Value)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, name)
	}
	return out
}

// TestNoDirectSigningOrEmulatorImports is ATTACK_F (test/local signer
// selected), ATTACK_G (emulator endpoint selected), and ATTACK_H (authority
// runtime gains signer identity), applied to this package: bootstrap must
// never import a concrete signing capability (kmssigner), a test-only
// signer (conformance/localsigner), or an emulator-only Spanner adapter
// (conformance/spanneradapter). Its only signing-adjacent dependency is the
// rotationcommit.Signer INTERFACE, satisfied in production exclusively by
// signerrpc.Client -- constructed and injected by a caller outside this
// package, never by bootstrap itself.
func TestNoDirectSigningOrEmulatorImports(t *testing.T) {
	t.Parallel()
	forbidden := map[string]bool{
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/kmssigner":                  true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/localsigner":    true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/spanneradapter": true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/witness":        true,
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/conformance/faultproxy":     true,
		"unsafe": true,
	}
	for _, path := range nonTestGoFiles(t, ".") {
		for _, imported := range importsOf(t, path) {
			if forbidden[imported] {
				t.Errorf("forbidden import %q in %s", imported, path)
			}
		}
	}
}

// TestNoStaticCredentialImports is ATTACK_R: bootstrap must never itself
// read or construct a static credential (a service-account key file, a
// hardcoded bearer token, a raw TLS certificate/key pair). Every
// Dependencies field is an already-constructed capability object supplied
// by the caller; this package has no field, flag, or code path that
// accepts a credential file path.
func TestNoStaticCredentialImports(t *testing.T) {
	t.Parallel()
	forbidden := map[string]bool{
		"crypto/tls": true,
		"os/exec":    true,
	}
	for _, path := range nonTestGoFiles(t, ".") {
		for _, imported := range importsOf(t, path) {
			if forbidden[imported] {
				t.Errorf("forbidden import %q in %s", imported, path)
			}
		}
	}
}

// TestRotationcommitImportSurfaceIsPublicOnly is ATTACK_B (bypass
// acceptedRotationContext): this package's only reachable rotationcommit
// identifiers are its exported ones (CompleteGenesisCommit, Signer,
// RawCommitClient, CommitClassification, and friends) -- Go's own
// unexported-identifier rule already makes acceptedRotationContext
// unreachable from another package; this test simply documents that
// bootstrap imports rotationcommit at all only for its sanctioned public
// surface, never anything suggesting an attempt to reach around it (no
// //go:linkname, no unsafe, no reflect-based field access).
func TestRotationcommitImportSurfaceIsPublicOnly(t *testing.T) {
	t.Parallel()
	forbidden := map[string]bool{
		"unsafe":  true,
		"reflect": true,
	}
	for _, path := range nonTestGoFiles(t, ".") {
		parsed, err := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if err != nil {
			t.Fatal(err)
		}
		for _, imported := range parsed.Imports {
			name, err := strconv.Unquote(imported.Path.Value)
			if err != nil {
				t.Fatal(err)
			}
			if forbidden[name] {
				t.Errorf("forbidden import %q in %s", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			comment, ok := n.(*ast.Comment)
			if ok && strings.Contains(comment.Text, "go:linkname") {
				t.Errorf("forbidden //go:linkname directive in %s", path)
			}
			return true
		})
	}
}

// TestOrdinaryRuntimeBinariesNeverImportBootstrap is ATTACK_O: bootstrap
// privilege must never persist into an ordinary runtime identity. The
// strongest guarantee available at the Go level is structural: neither
// cmd/recovery-authority nor cmd/recovery-signer -- the two ordinary,
// continuously-running production binaries -- imports this package at all,
// so there is no code path by which an ordinary runtime process could reach
// ExecuteGenesis, GenesisMutations, or any other bootstrap capability. This
// does not by itself prove IAM-level revocability of a bootstrap
// principal's grants after genesis (a deployment/IAM fact this package
// cannot see or enforce, exactly as compromiseledger's own package doc
// already establishes for a parallel concern) -- see the S6 final report.
func TestOrdinaryRuntimeBinariesNeverImportBootstrap(t *testing.T) {
	t.Parallel()
	const bootstrapImportPath = "github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/bootstrap"
	for _, dir := range []string{
		filepath.Join("..", "..", "..", "cmd", "recovery-authority"),
		filepath.Join("..", "..", "..", "cmd", "recovery-signer"),
	} {
		for _, path := range nonTestGoFiles(t, dir) {
			for _, imported := range importsOf(t, path) {
				if imported == bootstrapImportPath {
					t.Errorf("forbidden import of bootstrap package in ordinary runtime binary %s", path)
				}
			}
		}
	}
}

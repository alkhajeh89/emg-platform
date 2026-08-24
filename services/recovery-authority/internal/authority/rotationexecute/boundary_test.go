package rotationexecute_test

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

// TestRotationExecuteNeverImportsBootstrap proves, at the source level,
// domain separation from genesis: this package never imports bootstrap and
// never references its genesis-only vocabulary (GenesisRequest,
// GenesisMutations, DomainNewEpochGenesis, ExecuteGenesis). Ordinary
// rotation and genesis remain two structurally distinct paths.
func TestRotationExecuteNeverImportsBootstrap(t *testing.T) {
	t.Parallel()
	forbiddenImports := map[string]bool{
		"github.com/alkhajeh89/emg-platform/services/recovery-authority/internal/authority/bootstrap": true,
	}
	forbiddenIdentifiers := map[string]bool{
		"GenesisRequest":        true,
		"GenesisMutations":      true,
		"ExecuteGenesis":        true,
		"DomainNewEpochGenesis": true,
		"CompleteGenesisCommit": true,
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
		if strings.Contains(string(data), "genesis/") {
			t.Errorf("%s references a genesis/-prefixed witness key literal -- ordinary rotation must use its own, distinct key namespace", path)
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
				t.Errorf("forbidden import %q in %s -- rotationexecute must never depend on bootstrap", name, path)
			}
		}
		ast.Inspect(parsed, func(n ast.Node) bool {
			if ident, ok := n.(*ast.Ident); ok && forbiddenIdentifiers[ident.Name] {
				t.Errorf("forbidden reference to genesis-only identifier %q in %s", ident.Name, path)
			}
			return true
		})
	}
}

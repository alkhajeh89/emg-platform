package spannerprod

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

func TestProductionAdapterForbiddenAPIBoundary(t *testing.T) {
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/spanner":       true,
		"cloud.google.com/go/spanner/apiv1": true,
		"cloud.google.com/go/storage":       true,
	}
	forbiddenImportFragments := []string{
		"gax-go",
		"/kms/",
		"/iam/",
		"/serviceaccount/",
		"/resourcemanager/",
	}
	forbiddenSelectors := map[string]bool{
		"ReadWriteTransaction": true,
		"Apply":                true,
		"BeginTransaction":     true,
		"Read":                 true,
		"ExecuteSql":           true,
	}

	entries, err := os.ReadDir(".")
	if err != nil {
		t.Fatal(err)
	}
	for _, entry := range entries {
		if entry.IsDir() || filepath.Ext(entry.Name()) != ".go" || strings.HasSuffix(entry.Name(), "_test.go") {
			continue
		}
		parsed, parseErr := parser.ParseFile(token.NewFileSet(), entry.Name(), nil, 0)
		if parseErr != nil {
			t.Fatal(parseErr)
		}
		for _, imported := range parsed.Imports {
			name, unquoteErr := strconv.Unquote(imported.Path.Value)
			if unquoteErr != nil {
				t.Fatal(unquoteErr)
			}
			if forbiddenImports[name] {
				t.Errorf("forbidden production adapter import %q in %s", name, entry.Name())
			}
			for _, fragment := range forbiddenImportFragments {
				if strings.Contains(name, fragment) {
					t.Errorf("forbidden production adapter import %q in %s", name, entry.Name())
				}
			}
		}
		ast.Inspect(parsed, func(node ast.Node) bool {
			selector, ok := node.(*ast.SelectorExpr)
			if ok && forbiddenSelectors[selector.Sel.Name] {
				t.Errorf("forbidden production adapter API %s in %s", selector.Sel.Name, entry.Name())
			}
			return true
		})
	}
}

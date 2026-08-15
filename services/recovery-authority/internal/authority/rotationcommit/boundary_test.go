package rotationcommit_test

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

func TestAuthorityImportBoundary(t *testing.T) {
	t.Parallel()
	root := filepath.Clean("..")
	forbiddenImports := map[string]bool{
		"cloud.google.com/go/spanner":       true,
		"cloud.google.com/go/spanner/apiv1": true,
		"unsafe":                            true,
	}
	err := filepath.WalkDir(root, func(path string, entry os.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}
		if entry.IsDir() || !strings.HasSuffix(path, ".go") || strings.HasSuffix(path, "_test.go") {
			return nil
		}
		parsed, parseErr := parser.ParseFile(token.NewFileSet(), path, nil, parser.ImportsOnly)
		if parseErr != nil {
			return parseErr
		}
		for _, imported := range parsed.Imports {
			name, unquoteErr := strconv.Unquote(imported.Path.Value)
			if unquoteErr != nil {
				return unquoteErr
			}
			if forbiddenImports[name] {
				t.Errorf("forbidden authority import %q in %s", name, path)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}

func TestAcceptedContextHasNoExportedTypeOrConstructor(t *testing.T) {
	t.Parallel()
	files, err := filepath.Glob("*.go")
	if err != nil {
		t.Fatal(err)
	}
	for _, path := range files {
		if strings.HasSuffix(path, "_test.go") {
			continue
		}
		parsed, parseErr := parser.ParseFile(token.NewFileSet(), path, nil, 0)
		if parseErr != nil {
			t.Fatal(parseErr)
		}
		for _, declaration := range parsed.Decls {
			switch typed := declaration.(type) {
			case *ast.GenDecl:
				for _, specification := range typed.Specs {
					if typeSpec, ok := specification.(*ast.TypeSpec); ok &&
						ast.IsExported(typeSpec.Name.Name) &&
						strings.Contains(typeSpec.Name.Name, "AcceptedRotationContext") {
						t.Errorf("exported accepted context type %s", typeSpec.Name.Name)
					}
				}
			case *ast.FuncDecl:
				if ast.IsExported(typed.Name.Name) && strings.Contains(typed.Name.Name, "AcceptedRotationContext") {
					t.Errorf("exported accepted context function %s", typed.Name.Name)
				}
			}
		}
	}
}

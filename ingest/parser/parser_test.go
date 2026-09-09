package parser_test

import (
	"context"
	"os"
	"path/filepath"
	"testing"

	"github.com/rantoinne/ncm/ingest/parser"
)

func TestParseAndExtractGo(t *testing.T) {
	root := filepath.Join("testdata")
	path := filepath.Join(root, "sample.go")
	arts, err := parser.ParseAndExtract(context.Background(), root, parser.LanguageFiles{
		"go": {mustAbs(t, path)},
	})
	if err != nil {
		t.Fatal(err)
	}
	if len(arts) != 1 {
		t.Fatalf("artifacts: %d", len(arts))
	}
	art := arts[0]
	if art.Package != "main" {
		t.Fatalf("package: %q", art.Package)
	}
	names := symbolNames(art)
	for _, want := range []string{"Helper", "nested", "Config", "Store"} {
		if !names[want] {
			t.Fatalf("missing symbol %s in %v", want, names)
		}
	}
	// Helper should call nested
	for _, s := range art.Symbols {
		if s.Name == "Helper" {
			if !contains(s.Calls, "nested") {
				t.Fatalf("Helper calls: %v", s.Calls)
			}
			if s.ID != "sample.go#Helper" {
				t.Fatalf("id: %s", s.ID)
			}
		}
	}
}

func TestParseAndExtractPython(t *testing.T) {
	root := filepath.Join("testdata")
	path := filepath.Join(root, "sample.py")
	arts, err := parser.ParseAndExtract(context.Background(), root, parser.LanguageFiles{
		"python": {mustAbs(t, path)},
	})
	if err != nil {
		t.Fatal(err)
	}
	art := arts[0]
	if !contains(art.Imports, "os") || !contains(art.Imports, "pathlib") {
		t.Fatalf("imports: %v", art.Imports)
	}
	names := symbolNames(art)
	for _, want := range []string{"Greeter", "greet", "main", "hello"} {
		if !names[want] {
			t.Fatalf("missing symbol %s", want)
		}
	}
}

func TestParseAndExtractTypeScript(t *testing.T) {
	root := filepath.Join("testdata")
	path := filepath.Join(root, "sample.ts")
	arts, err := parser.ParseAndExtract(context.Background(), root, parser.LanguageFiles{
		"typescript": {mustAbs(t, path)},
	})
	if err != nil {
		t.Fatal(err)
	}
	art := arts[0]
	if !contains(art.Imports, "fs") || !contains(art.Imports, "./config") {
		t.Fatalf("imports: %v", art.Imports)
	}
	names := symbolNames(art)
	for _, want := range []string{"User", "Service", "helper", "arrow", "ID", "run"} {
		if !names[want] {
			t.Fatalf("missing symbol %s in %v", want, names)
		}
	}
}

func TestGetLanguage(t *testing.T) {
	for _, lang := range []string{"go", "python", "typescript", "tsx", "javascript"} {
		if parser.GetLanguage(lang) == nil {
			t.Fatalf("nil language for %s", lang)
		}
	}
	if parser.GetLanguage("cobol") != nil {
		t.Fatal("expected nil for unknown language")
	}
}

func mustAbs(t *testing.T, p string) string {
	t.Helper()
	abs, err := filepath.Abs(p)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := os.Stat(abs); err != nil {
		t.Fatal(err)
	}
	return abs
}

func symbolNames(art parser.FileArtifact) map[string]bool {
	m := make(map[string]bool)
	for _, s := range art.Symbols {
		m[s.Name] = true
	}
	return m
}

func contains(ss []string, want string) bool {
	for _, s := range ss {
		if s == want {
			return true
		}
	}
	return false
}

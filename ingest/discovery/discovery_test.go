package discovery_test

import (
	"os"
	"path/filepath"
	"testing"

	"github.com/rantoinne/ncm/ingest/discovery"
)

func TestScanAndDiscoverLanguages(t *testing.T) {
	root := t.TempDir()

	mustWrite(t, filepath.Join(root, "go.mod"), "module example.com/app\n\ngo 1.23\n")
	mustWrite(t, filepath.Join(root, "main.go"), "package main\n")
	mustWrite(t, filepath.Join(root, "pkg", "util.go"), "package pkg\n")
	mustWrite(t, filepath.Join(root, "app.py"), "print('hi')\n")
	mustWrite(t, filepath.Join(root, "web", "package.json"), "{}\n")
	mustWrite(t, filepath.Join(root, "web", "src", "index.ts"), "console.log(1)\n")
	mustWrite(t, filepath.Join(root, "web", "src", "App.tsx"), "export const App = () => null\n")
	mustWrite(t, filepath.Join(root, "web", "src", "util.js"), "export const x = 1\n")
	mustWrite(t, filepath.Join(root, "pyproject.toml"), "[project]\nname='app'\n")

	// Ignored paths
	mustWrite(t, filepath.Join(root, "node_modules", "x", "index.js"), "module.exports=1\n")
	mustWrite(t, filepath.Join(root, ".git", "config"), "")
	mustWrite(t, filepath.Join(root, "vendor", "lib.go"), "package lib\n")
	mustWrite(t, filepath.Join(root, ".venv", "lib", "x.py"), "pass\n")

	res, err := discovery.ScanAndDiscoverLanguages(root)
	if err != nil {
		t.Fatal(err)
	}
	if res.Stats["go"] != 2 {
		t.Fatalf("go files: got %d want 2", res.Stats["go"])
	}
	if res.Stats["python"] != 1 {
		t.Fatalf("python files: got %d want 1", res.Stats["python"])
	}
	if res.Stats["typescript"] != 1 {
		t.Fatalf("typescript files: got %d want 1", res.Stats["typescript"])
	}
	if res.Stats["tsx"] != 1 {
		t.Fatalf("tsx files: got %d want 1", res.Stats["tsx"])
	}
	if res.Stats["javascript"] != 1 {
		t.Fatalf("javascript files: got %d want 1", res.Stats["javascript"])
	}

	// Ignored dirs must not contribute
	for _, files := range res.Languages {
		for _, f := range files {
			if containsAny(f, "node_modules", "vendor", ".venv", ".git") {
				t.Fatalf("ignored path leaked: %s", f)
			}
		}
	}

	wantMods := map[string]bool{".": true, "web": true}
	for _, m := range res.ModuleRoots {
		delete(wantMods, m)
	}
	if len(wantMods) > 0 {
		t.Fatalf("missing module roots %v; got %v", wantMods, res.ModuleRoots)
	}
}

func mustWrite(t *testing.T, path, body string) {
	t.Helper()
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, []byte(body), 0o644); err != nil {
		t.Fatal(err)
	}
}

func containsAny(s string, parts ...string) bool {
	for _, p := range parts {
		if filepath.Base(filepath.Dir(s)) == p || // shallow
			len(s) > 0 && (filepath.Clean(s) != s) {
			_ = p
		}
		for _, seg := range splitPath(s) {
			if seg == p {
				return true
			}
		}
	}
	return false
}

func splitPath(s string) []string {
	var out []string
	for _, p := range filepath.SplitList(s) {
		_ = p
	}
	for s != "" && s != "." && s != string(filepath.Separator) {
		base := filepath.Base(s)
		out = append(out, base)
		parent := filepath.Dir(s)
		if parent == s {
			break
		}
		s = parent
	}
	return out
}

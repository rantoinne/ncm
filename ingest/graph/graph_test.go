package graph_test

import (
	"testing"

	"github.com/rantoinne/ncm/ingest/graph"
	"github.com/rantoinne/ncm/ingest/parser"
)

func TestBuildImportEdge(t *testing.T) {
	files := []parser.FileArtifact{
		{
			RelPath:  "pkg/a.go",
			Language: "go",
			Package:  "pkg",
			Imports:  []string{"example.com/mod/other"},
			Symbols: []parser.Symbol{
				{ID: "pkg/a.go#Foo", Name: "Foo", Kind: "function", Calls: []string{"Bar"}},
			},
		},
		{
			RelPath:  "other/b.go",
			Language: "go",
			Package:  "other",
			Symbols: []parser.Symbol{
				{ID: "other/b.go#Bar", Name: "Bar", Kind: "function"},
			},
		},
	}

	g := graph.Build(files, "test-repo")

	var foundImport, foundCall, foundContains bool
	for _, e := range g.Edges {
		if e.Type == "IMPORTS" && e.From == "pkg/a.go" {
			foundImport = true
		}
		if e.Type == "CALLS" && e.From == "pkg/a.go#Foo" && e.To == "other/b.go#Bar" {
			foundCall = true
		}
		if e.Type == "CONTAINS" && e.From == "pkg/a.go" && e.To == "pkg/a.go#Foo" {
			foundContains = true
		}
	}
	if !foundImport {
		t.Fatal("missing IMPORTS edge")
	}
	if !foundCall {
		t.Fatal("missing CALLS edge Foo→Bar")
	}
	if !foundContains {
		t.Fatal("missing CONTAINS edge file→symbol")
	}

	var hasFile, hasPkg bool
	for _, n := range g.Nodes {
		if n.ID == "pkg/a.go" && n.Type == "File" {
			hasFile = true
		}
		if n.ID == "pkg:pkg" && n.Type == "Package" {
			hasPkg = true
		}
	}
	if !hasFile || !hasPkg {
		t.Fatalf("missing nodes file=%v pkg=%v", hasFile, hasPkg)
	}
}

func TestRelativeImportEdge(t *testing.T) {
	files := []parser.FileArtifact{
		{
			RelPath:  "src/a.ts",
			Language: "typescript",
			Imports:  []string{"./b"},
		},
		{
			RelPath:  "src/b.ts",
			Language: "typescript",
		},
	}
	g := graph.Build(files, "repo")
	found := false
	for _, e := range g.Edges {
		if e.Type == "IMPORTS" && e.From == "src/a.ts" && e.To == "src/b" {
			found = true
		}
	}
	if !found {
		t.Fatalf("expected relative IMPORTS to src/b; edges=%v", g.Edges)
	}
}

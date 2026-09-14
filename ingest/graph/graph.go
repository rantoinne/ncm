package graph

import (
	"fmt"
	"path"
	"path/filepath"
	"sort"
	"strings"

	"github.com/rantoinne/ncm/ingest/parser"
)

// Node is a graph entity.
type Node struct {
	ID    string         `json:"id"`
	Type  string         `json:"type"` // File, Package, Function, Module, Struct, Interface, Class, Type
	Label string         `json:"label"`
	Props map[string]any `json:"props,omitempty"`
}

// Edge is a directed relationship between nodes.
type Edge struct {
	ID         string   `json:"id"`
	Type       string   `json:"type"` // CONTAINS, IMPORTS, CALLS, DEPENDS_ON
	From       string   `json:"from"`
	To         string   `json:"to"`
	Confidence float64  `json:"confidence"`
	Evidence   []string `json:"evidence,omitempty"`
}

// Graph is the exported dependency graph.
type Graph struct {
	Nodes  []Node     `json:"nodes"`
	Edges  []Edge     `json:"edges"`
	Cycles [][]string `json:"cycles,omitempty"`
}

type pendingCall struct {
	fromID string
	name   string
}

type pendingRel struct {
	fromID   string
	name     string
	edgeType string
}

// Build constructs a dependency graph from file artifacts.
func Build(files []parser.FileArtifact, repoID string) Graph {
	b := newBuilder(repoID)
	for _, f := range files {
		b.addFile(f)
	}
	b.resolveCalls()
	b.resolveHeritage()
	b.addTestEdges()
	b.addPackageDeps()
	b.detectCycles()
	return b.export()
}

type builder struct {
	repoID     string
	nodes      map[string]Node
	edges      map[string]Edge
	byName     map[string][]string
	pkgDeps    map[string]map[string]struct{}
	pending    []pendingCall
	pendingExt []pendingRel
	cycles     [][]string
}

func newBuilder(repoID string) *builder {
	return &builder{
		repoID:  repoID,
		nodes:   make(map[string]Node),
		edges:   make(map[string]Edge),
		byName:  make(map[string][]string),
		pkgDeps: make(map[string]map[string]struct{}),
	}
}

func (b *builder) addNode(n Node) {
	if _, ok := b.nodes[n.ID]; !ok {
		b.nodes[n.ID] = n
	}
}

func (b *builder) addEdge(e Edge) {
	if e.ID == "" {
		e.ID = fmt.Sprintf("%s:%s->%s", e.Type, e.From, e.To)
	}
	if _, ok := b.edges[e.ID]; !ok {
		b.edges[e.ID] = e
	}
}

func (b *builder) addFile(f parser.FileArtifact) {
	fileID := filepath.ToSlash(f.RelPath)
	b.addNode(Node{
		ID:    fileID,
		Type:  "File",
		Label: path.Base(fileID),
		Props: map[string]any{
			"path":     fileID,
			"language": f.Language,
			"repo_id":  b.repoID,
		},
	})

	// Prefer directory path as stable package identity (matches import suffixes).
	pkgID := path.Dir(fileID)
	if pkgID == "." || pkgID == "" {
		if f.Package != "" {
			pkgID = f.Package
		} else {
			pkgID = "root"
		}
	}
	pkgNodeID := "pkg:" + pkgID
	b.addNode(Node{
		ID:    pkgNodeID,
		Type:  "Package",
		Label: pkgID,
		Props: map[string]any{
			"repo_id":      b.repoID,
			"go_package":   f.Package,
			"dir":          path.Dir(fileID),
		},
	})
	b.addEdge(Edge{
		Type:       "CONTAINS",
		From:       pkgNodeID,
		To:         fileID,
		Confidence: 1.0,
		Evidence:   []string{"package membership"},
	})

	for _, imp := range f.Imports {
		if resolved := resolveImportToFile(f, imp); resolved != "" {
			b.addEdge(Edge{
				Type:       "IMPORTS",
				From:       fileID,
				To:         resolved,
				Confidence: 0.9,
				Evidence:   []string{fmt.Sprintf("import %q", imp)},
			})
		} else {
			impID := "import:" + imp
			b.addNode(Node{
				ID:    impID,
				Type:  "Module",
				Label: imp,
				Props: map[string]any{"external": true},
			})
			b.addEdge(Edge{
				Type:       "IMPORTS",
				From:       fileID,
				To:         impID,
				Confidence: 0.7,
				Evidence:   []string{fmt.Sprintf("import %q", imp)},
			})
		}

		depPkg := packageFromImport(imp, f.Language)
		if depPkg != "" && depPkg != pkgID {
			if b.pkgDeps[pkgID] == nil {
				b.pkgDeps[pkgID] = make(map[string]struct{})
			}
			b.pkgDeps[pkgID][depPkg] = struct{}{}
		}
	}

	for _, sym := range f.Symbols {
		b.addNode(Node{
			ID:    sym.ID,
			Type:  symbolNodeType(sym.Kind),
			Label: sym.Name,
			Props: map[string]any{
				"kind":       sym.Kind,
				"signature":  sym.Signature,
				"start_line": sym.StartLine,
				"end_line":   sym.EndLine,
				"file":       fileID,
				"repo_id":    b.repoID,
			},
		})
		b.addEdge(Edge{
			Type:       "CONTAINS",
			From:       fileID,
			To:         sym.ID,
			Confidence: 1.0,
			Evidence:   []string{"AST extraction"},
		})

		short := sym.Name
		if i := strings.LastIndex(short, "."); i >= 0 {
			short = short[i+1:]
		}
		b.byName[sym.Name] = append(b.byName[sym.Name], sym.ID)
		if short != sym.Name {
			b.byName[short] = append(b.byName[short], sym.ID)
		}

		for _, call := range sym.Calls {
			b.pending = append(b.pending, pendingCall{fromID: sym.ID, name: call})
		}

		for _, base := range sym.Extends {
			b.pendingExt = append(b.pendingExt, pendingRel{fromID: sym.ID, name: base, edgeType: "EXTENDS"})
		}
		for _, iface := range sym.Implements {
			b.pendingExt = append(b.pendingExt, pendingRel{fromID: sym.ID, name: iface, edgeType: "IMPLEMENTS"})
		}
	}
}

func symbolNodeType(kind string) string {
	switch kind {
	case "struct":
		return "Struct"
	case "interface":
		return "Interface"
	case "class":
		return "Class"
	case "type":
		return "Type"
	case "method":
		return "Function"
	default:
		return "Function"
	}
}

func (b *builder) resolveCalls() {
	for _, pc := range b.pending {
		targets := b.byName[pc.name]
		if len(targets) == 0 {
			if i := strings.LastIndex(pc.name, "."); i >= 0 {
				targets = b.byName[pc.name[i+1:]]
			}
		}
		switch {
		case len(targets) == 1:
			b.addEdge(Edge{
				Type:       "CALLS",
				From:       pc.fromID,
				To:         targets[0],
				Confidence: 0.85,
				Evidence:   []string{fmt.Sprintf("call %s", pc.name)},
			})
		case len(targets) > 1:
			b.addEdge(Edge{
				Type:       "CALLS",
				From:       pc.fromID,
				To:         targets[0],
				Confidence: 0.4,
				Evidence:   []string{fmt.Sprintf("ambiguous call %s", pc.name)},
			})
		default:
			unresolved := "call:" + pc.name
			b.addNode(Node{
				ID:    unresolved,
				Type:  "Function",
				Label: pc.name,
				Props: map[string]any{"unresolved": true},
			})
			b.addEdge(Edge{
				Type:       "CALLS",
				From:       pc.fromID,
				To:         unresolved,
				Confidence: 0.3,
				Evidence:   []string{fmt.Sprintf("unresolved call %s", pc.name)},
			})
		}
	}
}

func (b *builder) resolveHeritage() {
	for _, pr := range b.pendingExt {
		targets := b.byName[pr.name]
		if len(targets) == 0 {
			if i := strings.LastIndex(pr.name, "."); i >= 0 {
				targets = b.byName[pr.name[i+1:]]
			}
		}
		if len(targets) == 0 {
			extID := "type:" + pr.name
			b.addNode(Node{
				ID:    extID,
				Type:  "Type",
				Label: pr.name,
				Props: map[string]any{"external": true},
			})
			b.addEdge(Edge{
				Type:       pr.edgeType,
				From:       pr.fromID,
				To:         extID,
				Confidence: 0.5,
				Evidence:   []string{fmt.Sprintf("%s %s", pr.edgeType, pr.name)},
			})
			continue
		}
		conf := 0.85
		if len(targets) > 1 {
			conf = 0.5
		}
		b.addEdge(Edge{
			Type:       pr.edgeType,
			From:       pr.fromID,
			To:         targets[0],
			Confidence: conf,
			Evidence:   []string{fmt.Sprintf("%s %s", pr.edgeType, pr.name)},
		})
	}
}

func (b *builder) addTestEdges() {
	for id, n := range b.nodes {
		if n.Type != "File" {
			continue
		}
		if !isTestFile(id) {
			continue
		}
		target := testTargetPath(id)
		if target == "" {
			continue
		}
		if _, ok := b.nodes[target]; !ok {
			continue
		}
		b.addEdge(Edge{
			Type:       "TESTS",
			From:       id,
			To:         target,
			Confidence: 0.75,
			Evidence:   []string{"test file naming convention"},
		})
	}
}

func isTestFile(rel string) bool {
	base := path.Base(rel)
	if strings.HasSuffix(base, "_test.go") {
		return true
	}
	if strings.HasPrefix(base, "test_") && strings.HasSuffix(base, ".py") {
		return true
	}
	if strings.HasSuffix(base, "_test.py") {
		return true
	}
	if strings.Contains(base, ".test.") || strings.Contains(base, ".spec.") {
		return true
	}
	return false
}

func testTargetPath(testPath string) string {
	base := path.Base(testPath)
	dir := path.Dir(testPath)
	switch {
	case strings.HasSuffix(base, "_test.go"):
		return path.Join(dir, strings.TrimSuffix(base, "_test.go")+".go")
	case strings.HasPrefix(base, "test_") && strings.HasSuffix(base, ".py"):
		return path.Join(dir, strings.TrimPrefix(base, "test_"))
	case strings.HasSuffix(base, "_test.py"):
		return path.Join(dir, strings.TrimSuffix(base, "_test.py")+".py")
	case strings.Contains(base, ".test."):
		return path.Join(dir, strings.Replace(base, ".test.", ".", 1))
	case strings.Contains(base, ".spec."):
		return path.Join(dir, strings.Replace(base, ".spec.", ".", 1))
	}
	return ""
}

func (b *builder) addPackageDeps() {
	for pkg, deps := range b.pkgDeps {
		from := "pkg:" + pkg
		for dep := range deps {
			to := "pkg:" + dep
			b.addNode(Node{ID: to, Type: "Package", Label: dep, Props: map[string]any{}})
			b.addEdge(Edge{
				Type:       "DEPENDS_ON",
				From:       from,
				To:         to,
				Confidence: 0.8,
				Evidence:   []string{"import graph"},
			})
		}
	}
}

func (b *builder) detectCycles() {
	adj := make(map[string][]string)
	for _, e := range b.edges {
		if e.Type != "DEPENDS_ON" {
			continue
		}
		adj[e.From] = append(adj[e.From], e.To)
	}

	const (
		white = 0
		gray  = 1
		black = 2
	)
	color := make(map[string]int)
	var stack []string
	var cycles [][]string

	var dfs func(u string)
	dfs = func(u string) {
		color[u] = gray
		stack = append(stack, u)
		for _, v := range adj[u] {
			switch color[v] {
			case white:
				dfs(v)
			case gray:
				idx := -1
				for i, s := range stack {
					if s == v {
						idx = i
						break
					}
				}
				if idx >= 0 {
					cyc := append([]string{}, stack[idx:]...)
					cyc = append(cyc, v)
					cycles = append(cycles, cyc)
				}
			}
		}
		stack = stack[:len(stack)-1]
		color[u] = black
	}

	nodes := make([]string, 0, len(adj))
	for n := range adj {
		nodes = append(nodes, n)
	}
	sort.Strings(nodes)
	for _, n := range nodes {
		if color[n] == white {
			dfs(n)
		}
	}
	b.cycles = cycles
}

func (b *builder) export() Graph {
	nodes := make([]Node, 0, len(b.nodes))
	for _, n := range b.nodes {
		nodes = append(nodes, n)
	}
	sort.Slice(nodes, func(i, j int) bool { return nodes[i].ID < nodes[j].ID })

	edges := make([]Edge, 0, len(b.edges))
	for _, e := range b.edges {
		edges = append(edges, e)
	}
	sort.Slice(edges, func(i, j int) bool { return edges[i].ID < edges[j].ID })

	return Graph{Nodes: nodes, Edges: edges, Cycles: b.cycles}
}

func resolveImportToFile(f parser.FileArtifact, imp string) string {
	if !(strings.HasPrefix(imp, "./") || strings.HasPrefix(imp, "../")) {
		return ""
	}
	dir := path.Dir(filepath.ToSlash(f.RelPath))
	joined := path.Clean(path.Join(dir, imp))
	return joined
}

func packageFromImport(imp, lang string) string {
	imp = strings.TrimSpace(imp)
	if imp == "" || strings.HasPrefix(imp, ".") {
		return ""
	}
	switch lang {
	case "go":
		parts := strings.Split(imp, "/")
		if len(parts) >= 2 {
			return strings.Join(parts[len(parts)-2:], "/")
		}
		return imp
	case "python":
		return strings.Split(imp, ".")[0]
	default:
		return imp
	}
}

package parser

import (
	"fmt"
	"path/filepath"
	"strings"

	sitter "github.com/smacker/go-tree-sitter"
)

// Extract builds a FileArtifact from a parsed tree and source content.
func Extract(path string, relPath string, lang string, tree *sitter.Tree, content []byte) FileArtifact {
	art := FileArtifact{
		Path:     path,
		RelPath:  filepath.ToSlash(relPath),
		Language: lang,
	}
	if tree == nil {
		return art
	}
	root := tree.RootNode()
	switch lang {
	case "go":
		extractGo(&art, root, content)
	case "python":
		extractPython(&art, root, content)
	case "typescript", "tsx", "javascript":
		extractTSJS(&art, root, content)
	}
	return art
}

func symbolID(relPath, name string) string {
	return fmt.Sprintf("%s#%s", filepath.ToSlash(relPath), name)
}

// StableSymbolID builds {repo}:{commit}:{path}#{name} when repo/commit known.
func StableSymbolID(repoID, commit, relPath, name string) string {
	rel := filepath.ToSlash(relPath)
	if repoID == "" || commit == "" {
		return symbolID(rel, name)
	}
	if len(commit) > 12 {
		commit = commit[:12]
	}
	return fmt.Sprintf("%s:%s:%s#%s", repoID, commit, rel, name)
}

// StampStableIDs rewrites symbol IDs on artifacts using repo + commit.
func StampStableIDs(arts []FileArtifact, repoID, commit string) {
	for i := range arts {
		arts[i].RepoID = repoID
		arts[i].CommitSHA = commit
		for j := range arts[i].Symbols {
			name := arts[i].Symbols[j].Name
			arts[i].Symbols[j].ID = StableSymbolID(repoID, commit, arts[i].RelPath, name)
		}
	}
}

func nodeText(n *sitter.Node, content []byte) string {
	if n == nil {
		return ""
	}
	return string(content[n.StartByte():n.EndByte()])
}

func childByField(n *sitter.Node, field string) *sitter.Node {
	if n == nil {
		return nil
	}
	return n.ChildByFieldName(field)
}

func walk(n *sitter.Node, fn func(*sitter.Node) bool) {
	if n == nil {
		return
	}
	if !fn(n) {
		return
	}
	for i := 0; i < int(n.NamedChildCount()); i++ {
		walk(n.NamedChild(i), fn)
	}
}

func collectComments(root *sitter.Node, content []byte, types map[string]bool) []string {
	var out []string
	walk(root, func(n *sitter.Node) bool {
		if types[n.Type()] {
			t := strings.TrimSpace(nodeText(n, content))
			if t != "" {
				out = append(out, t)
			}
		}
		return true
	})
	return out
}

func collectCalls(n *sitter.Node, content []byte) []string {
	seen := make(map[string]struct{})
	var calls []string
	walk(n, func(c *sitter.Node) bool {
		if c.Type() != "call_expression" && c.Type() != "call" {
			return true
		}
		fn := childByField(c, "function")
		if fn == nil {
			fn = c.NamedChild(0)
		}
		name := callName(fn, content)
		if name == "" {
			return true
		}
		if _, ok := seen[name]; ok {
			return true
		}
		seen[name] = struct{}{}
		calls = append(calls, name)
		return true
	})
	return calls
}

func callName(n *sitter.Node, content []byte) string {
	if n == nil {
		return ""
	}
	switch n.Type() {
	case "identifier", "property_identifier", "type_identifier":
		return nodeText(n, content)
	case "selector_expression", "member_expression", "attribute":
		// Keep last segment for simple resolution (obj.Method → Method)
		obj := childByField(n, "object")
		field := childByField(n, "field")
		if field == nil {
			field = childByField(n, "property")
		}
		if field == nil {
			field = childByField(n, "attribute")
		}
		if field != nil {
			base := nodeText(field, content)
			if obj != nil && (obj.Type() == "identifier" || obj.Type() == "type_identifier") {
				return nodeText(obj, content) + "." + base
			}
			return base
		}
		return nodeText(n, content)
	default:
		return ""
	}
}

func extractGo(art *FileArtifact, root *sitter.Node, content []byte) {
	art.Comments = collectComments(root, content, map[string]bool{
		"comment": true,
	})

	walk(root, func(n *sitter.Node) bool {
		switch n.Type() {
		case "package_clause":
			if id := n.NamedChild(0); id != nil {
				art.Package = nodeText(id, content)
			}
		case "import_declaration":
			extractGoImports(art, n, content)
		case "function_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			body := childByField(n, "body")
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "function",
				Signature: truncateSig(nodeText(n, content)),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Calls:     collectCalls(body, content),
			})
		case "method_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			recv := childByField(n, "receiver")
			if recv != nil {
				// Prefer Type.Method naming when possible
				rtype := findGoReceiverType(recv, content)
				if rtype != "" {
					name = rtype + "." + name
				}
			}
			body := childByField(n, "body")
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "method",
				Signature: truncateSig(nodeText(n, content)),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Calls:     collectCalls(body, content),
			})
		case "type_declaration":
			extractGoTypes(art, n, content)
		}
		return true
	})
}

func extractGoImports(art *FileArtifact, n *sitter.Node, content []byte) {
	foundSpec := false
	walk(n, func(c *sitter.Node) bool {
		if c.Type() == "import_spec" {
			foundSpec = true
			pathNode := childByField(c, "path")
			if pathNode != nil {
				p := strings.Trim(nodeText(pathNode, content), `"`)
				art.Imports = appendUnique(art.Imports, p)
			}
			return false
		}
		return true
	})
	// Single-line: import "fmt" may not wrap import_spec in all grammars
	if !foundSpec {
		walk(n, func(c *sitter.Node) bool {
			if c.Type() == "interpreted_string_literal" {
				p := strings.Trim(nodeText(c, content), `"`)
				art.Imports = appendUnique(art.Imports, p)
				return false
			}
			return true
		})
	}
}

func appendUnique(ss []string, v string) []string {
	if v == "" {
		return ss
	}
	for _, s := range ss {
		if s == v {
			return ss
		}
	}
	return append(ss, v)
}

func findGoReceiverType(recv *sitter.Node, content []byte) string {
	var typ string
	walk(recv, func(n *sitter.Node) bool {
		switch n.Type() {
		case "type_identifier":
			typ = nodeText(n, content)
			return false
		case "pointer_type":
			return true
		}
		return true
	})
	return typ
}

func extractGoTypes(art *FileArtifact, n *sitter.Node, content []byte) {
	walk(n, func(c *sitter.Node) bool {
		if c.Type() != "type_spec" {
			return true
		}
		nameNode := childByField(c, "name")
		typeNode := childByField(c, "type")
		if nameNode == nil {
			return true
		}
		name := nodeText(nameNode, content)
		kind := "type"
		if typeNode != nil {
			switch typeNode.Type() {
			case "struct_type":
				kind = "struct"
			case "interface_type":
				kind = "interface"
			}
		}
		art.Symbols = append(art.Symbols, Symbol{
			ID:        symbolID(art.RelPath, name),
			Name:      name,
			Kind:      kind,
			Signature: truncateSig(nodeText(c, content)),
			StartLine: c.StartPoint().Row + 1,
			EndLine:   c.EndPoint().Row + 1,
		})
		return true
	})
}

func extractPython(art *FileArtifact, root *sitter.Node, content []byte) {
	art.Comments = collectComments(root, content, map[string]bool{
		"comment": true,
	})

	walk(root, func(n *sitter.Node) bool {
		switch n.Type() {
		case "import_statement", "import_from_statement":
			extractPythonImport(art, n, content)
		case "function_definition":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			body := childByField(n, "body")
			kind := "function"
			// Heuristic: methods live under class_definition
			if parentKind(n) == "block" && grandparentKind(n) == "class_definition" {
				kind = "method"
			}
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      kind,
				Signature: truncateSig(firstLine(nodeText(n, content))),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Calls:     collectCalls(body, content),
			})
		case "class_definition":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			bases := pythonBases(n, content)
			art.Symbols = append(art.Symbols, Symbol{
				ID:         symbolID(art.RelPath, name),
				Name:       name,
				Kind:       "class",
				Signature:  truncateSig(firstLine(nodeText(n, content))),
				StartLine:  n.StartPoint().Row + 1,
				EndLine:    n.EndPoint().Row + 1,
				Extends:    bases,
				Implements: nil,
			})
		}
		return true
	})
}

func extractPythonImport(art *FileArtifact, n *sitter.Node, content []byte) {
	switch n.Type() {
	case "import_statement":
		walk(n, func(c *sitter.Node) bool {
			if c.Type() == "dotted_name" || c.Type() == "aliased_import" {
				name := c
				if c.Type() == "aliased_import" {
					name = childByField(c, "name")
				}
				if name != nil {
					art.Imports = append(art.Imports, nodeText(name, content))
				}
				return false
			}
			return true
		})
	case "import_from_statement":
		mod := childByField(n, "module_name")
		if mod != nil {
			art.Imports = append(art.Imports, nodeText(mod, content))
		}
	}
}

func extractTSJS(art *FileArtifact, root *sitter.Node, content []byte) {
	art.Comments = collectComments(root, content, map[string]bool{
		"comment":       true,
		"line_comment":  true,
		"block_comment": true,
		"html_comment":  true,
	})

	walk(root, func(n *sitter.Node) bool {
		switch n.Type() {
		case "import_statement":
			extractTSImport(art, n, content)
		case "function_declaration", "generator_function_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			body := childByField(n, "body")
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "function",
				Signature: truncateSig(firstLine(nodeText(n, content))),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Calls:     collectCalls(body, content),
			})
		case "method_definition":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			body := childByField(n, "body")
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "method",
				Signature: truncateSig(firstLine(nodeText(n, content))),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Calls:     collectCalls(body, content),
			})
		case "class_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			ext, impl := tsHeritage(n, content)
			art.Symbols = append(art.Symbols, Symbol{
				ID:         symbolID(art.RelPath, name),
				Name:       name,
				Kind:       "class",
				Signature:  truncateSig(firstLine(nodeText(n, content))),
				StartLine:  n.StartPoint().Row + 1,
				EndLine:    n.EndPoint().Row + 1,
				Extends:    ext,
				Implements: impl,
			})
		case "interface_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			ext, _ := tsHeritage(n, content)
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "interface",
				Signature: truncateSig(firstLine(nodeText(n, content))),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
				Extends:   ext,
			})
		case "type_alias_declaration":
			nameNode := childByField(n, "name")
			if nameNode == nil {
				return true
			}
			name := nodeText(nameNode, content)
			art.Symbols = append(art.Symbols, Symbol{
				ID:        symbolID(art.RelPath, name),
				Name:      name,
				Kind:      "type",
				Signature: truncateSig(firstLine(nodeText(n, content))),
				StartLine: n.StartPoint().Row + 1,
				EndLine:   n.EndPoint().Row + 1,
			})
		case "lexical_declaration", "variable_declaration":
			extractTSArrowFuncs(art, n, content)
		}
		return true
	})
}

func pythonBases(classNode *sitter.Node, content []byte) []string {
	var bases []string
	argList := childByField(classNode, "superclasses")
	if argList == nil {
		// Some grammars use argument_list as named child
		for i := 0; i < int(classNode.NamedChildCount()); i++ {
			ch := classNode.NamedChild(i)
			if ch.Type() == "argument_list" {
				argList = ch
				break
			}
		}
	}
	if argList == nil {
		return bases
	}
	walk(argList, func(c *sitter.Node) bool {
		if c.Type() == "identifier" || c.Type() == "attribute" {
			bases = append(bases, nodeText(c, content))
			return false
		}
		return true
	})
	return bases
}

func tsHeritage(classNode *sitter.Node, content []byte) (extends, implements []string) {
	for i := 0; i < int(classNode.NamedChildCount()); i++ {
		c := classNode.NamedChild(i)
		switch c.Type() {
		case "class_heritage", "extends_clause", "heritage_clause":
			walk(c, func(t *sitter.Node) bool {
				if t.Type() == "type_identifier" || t.Type() == "identifier" {
					extends = append(extends, nodeText(t, content))
					return false
				}
				return true
			})
		case "implements_clause":
			walk(c, func(t *sitter.Node) bool {
				if t.Type() == "type_identifier" || t.Type() == "identifier" {
					implements = append(implements, nodeText(t, content))
					return false
				}
				return true
			})
		}
	}
	return extends, implements
}

func extractTSImport(art *FileArtifact, n *sitter.Node, content []byte) {
	walk(n, func(c *sitter.Node) bool {
		if c.Type() == "string" {
			p := strings.Trim(nodeText(c, content), `'"`)
			if p != "" {
				art.Imports = append(art.Imports, p)
			}
			return false
		}
		return true
	})
}

func extractTSArrowFuncs(art *FileArtifact, n *sitter.Node, content []byte) {
	walk(n, func(c *sitter.Node) bool {
		if c.Type() != "variable_declarator" {
			return true
		}
		nameNode := childByField(c, "name")
		value := childByField(c, "value")
		if nameNode == nil || value == nil {
			return true
		}
		if value.Type() != "arrow_function" && value.Type() != "function" {
			return true
		}
		name := nodeText(nameNode, content)
		art.Symbols = append(art.Symbols, Symbol{
			ID:        symbolID(art.RelPath, name),
			Name:      name,
			Kind:      "function",
			Signature: truncateSig(firstLine(nodeText(c, content))),
			StartLine: c.StartPoint().Row + 1,
			EndLine:   c.EndPoint().Row + 1,
			Calls:     collectCalls(value, content),
		})
		return true
	})
}

func parentKind(n *sitter.Node) string {
	p := n.Parent()
	if p == nil {
		return ""
	}
	return p.Type()
}

func grandparentKind(n *sitter.Node) string {
	p := n.Parent()
	if p == nil {
		return ""
	}
	gp := p.Parent()
	if gp == nil {
		return ""
	}
	return gp.Type()
}

func firstLine(s string) string {
	if i := strings.IndexByte(s, '\n'); i >= 0 {
		return strings.TrimSpace(s[:i])
	}
	return strings.TrimSpace(s)
}

func truncateSig(s string) string {
	s = strings.TrimSpace(s)
	const max = 200
	if len(s) > max {
		return s[:max] + "…"
	}
	return s
}

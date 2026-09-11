package discovery

import (
	"io/fs"
	"path/filepath"
	"sort"
)

// IgnoreDirs are directory names skipped during discovery walks.
var IgnoreDirs = map[string]bool{
	".git":         true,
	".plans":       true,
	".vscode":      true,
	".idea":        true,
	"node_modules": true,
	"vendor":       true,
	"dist":         true,
	"build":        true,
	".venv":        true,
	"venv":         true,
	"__pycache__":  true,
	"target":       true,
	".next":        true,
	".turbo":       true,
	"coverage":     true,
	".cache":       true,
	".yarn":        true,
	"yarn_cache":   true,
}

// IgnoreFiles are file names skipped during discovery walks.
var IgnoreFiles = map[string]bool{
	".DS_Store":      true,
	".gitattributes": true,
	".gitignore":     true,
}

// ExtToLanguage maps file extensions to language identifiers.
var ExtToLanguage = map[string]string{
	".go":  "go",
	".py":  "python",
	".ts":  "typescript",
	".tsx": "tsx",
	".js":  "javascript",
	".jsx": "javascript",
	".mjs": "javascript",
	".cjs": "javascript",
}

// ModuleMarkers are filenames that indicate a module/package root.
var ModuleMarkers = map[string]bool{
	"go.mod":           true,
	"package.json":     true,
	"pyproject.toml":   true,
	"requirements.txt": true,
}

// DiscoveryResult holds languages, module roots, and scan stats for a repo.
type DiscoveryResult struct {
	Root        string              `json:"root"`
	Languages   map[string][]string `json:"languages"`
	ModuleRoots []string            `json:"module_roots"`
	Stats       map[string]int      `json:"stats"`
}

// ScanAndDiscoverLanguages walks root and returns discovered source files by language.
func ScanAndDiscoverLanguages(root string) (*DiscoveryResult, error) {
	// TODO: Might be redundant given this is being called from Scan which already calls filepath.Abs
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}

	result := &DiscoveryResult{
		Root:      absRoot,
		Languages: make(map[string][]string),
		Stats:     make(map[string]int),
	}

	moduleSet := make(map[string]struct{})

	err = filepath.WalkDir(absRoot, func(path string, d fs.DirEntry, walkErr error) error {
		if walkErr != nil {
			return walkErr
		}

		name := d.Name()

		if d.IsDir() {
			if IgnoreDirs[name] {
				return filepath.SkipDir
			}
			return nil
		}

		if IgnoreFiles[name] {
			return nil
		}

		if ModuleMarkers[name] {
			dir := filepath.Dir(path)
			rel, relErr := filepath.Rel(absRoot, dir)
			if relErr != nil {
				rel = dir
			}
			if rel == "." {
				rel = "."
			}
			moduleSet[filepath.ToSlash(rel)] = struct{}{}
		}

		ext := filepath.Ext(name)
		lang, ok := ExtToLanguage[ext]
		if !ok {
			return nil
		}

		result.Languages[lang] = append(result.Languages[lang], path)
		result.Stats[lang]++
		result.Stats["files"]++
		return nil
	})
	if err != nil {
		return nil, err
	}

	modules := make([]string, 0, len(moduleSet))
	for m := range moduleSet {
		modules = append(modules, m)
	}
	sort.Strings(modules)
	result.ModuleRoots = modules
	result.Stats["module_roots"] = len(modules)

	for lang := range result.Languages {
		sort.Strings(result.Languages[lang])
	}

	return result, nil
}

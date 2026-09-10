package writer

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/rantoinne/ncm/ingest/discovery"
	"github.com/rantoinne/ncm/ingest/git"
	"github.com/rantoinne/ncm/ingest/graph"
	"github.com/rantoinne/ncm/ingest/parser"
)

// Manifest describes an indexed repository snapshot.
type Manifest struct {
	RepoID      string         `json:"repo_id"`
	RepoRoot    string         `json:"repo_root"`
	Root        string         `json:"root"` // alias of repo_root for Python consumers
	CommitSHA   string         `json:"commit_sha"`
	IndexedAt   time.Time      `json:"indexed_at"`
	ScannedAt   time.Time      `json:"scanned_at"` // alias of indexed_at
	Languages   map[string]int `json:"languages"`
	ModuleRoots []string       `json:"module_roots"`
	FileCount   int            `json:"file_count"`
	Version     string         `json:"version"`
}

// Checkpoint supports incremental indexing.
type Checkpoint struct {
	LastCommit   string            `json:"last_commit"`
	IndexedFiles map[string]string `json:"indexed_files"` // rel path → content hash
	UpdatedAt    time.Time         `json:"updated_at"`
}

// WriteManifest writes manifest.json.
func WriteManifest(outDir string, m Manifest) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	return writeJSON(filepath.Join(outDir, "manifest.json"), m)
}

// WriteFileArtifact writes one file artifact under files/.
func WriteFileArtifact(outDir string, art parser.FileArtifact) error {
	dir := filepath.Join(outDir, "files")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	name := SafePath(art.RelPath) + ".json"
	return writeJSON(filepath.Join(dir, name), art)
}

// WriteFileArtifacts writes all file artifacts.
func WriteFileArtifacts(outDir string, arts []parser.FileArtifact) error {
	for _, art := range arts {
		if err := WriteFileArtifact(outDir, art); err != nil {
			return err
		}
	}
	return nil
}

// WriteGraph writes graph.json.
func WriteGraph(outDir string, g graph.Graph) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	return writeJSON(filepath.Join(outDir, "graph.json"), g)
}

// WriteGit writes git.json.
func WriteGit(outDir string, g *git.GitArtifact) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	return writeJSON(filepath.Join(outDir, "git.json"), g)
}

// WriteCheckpoint writes checkpoint.json.
func WriteCheckpoint(outDir string, cp Checkpoint) error {
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	return writeJSON(filepath.Join(outDir, "checkpoint.json"), cp)
}

// ReadCheckpoint loads checkpoint.json if present.
func ReadCheckpoint(outDir string) (*Checkpoint, error) {
	path := filepath.Join(outDir, "checkpoint.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var cp Checkpoint
	if err := json.Unmarshal(data, &cp); err != nil {
		return nil, err
	}
	return &cp, nil
}

// LoadFileArtifacts reads all JSON artifacts from files/.
func LoadFileArtifacts(outDir string) ([]parser.FileArtifact, error) {
	dir := filepath.Join(outDir, "files")
	entries, err := os.ReadDir(dir)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var arts []parser.FileArtifact
	for _, e := range entries {
		if e.IsDir() || !strings.HasSuffix(e.Name(), ".json") {
			continue
		}
		data, err := os.ReadFile(filepath.Join(dir, e.Name()))
		if err != nil {
			return nil, err
		}
		var art parser.FileArtifact
		if err := json.Unmarshal(data, &art); err != nil {
			return nil, fmt.Errorf("%s: %w", e.Name(), err)
		}
		arts = append(arts, art)
	}
	return arts, nil
}

// RemoveFileArtifact deletes the artifact for a relative path if present.
func RemoveFileArtifact(outDir, relPath string) error {
	path := filepath.Join(outDir, "files", SafePath(relPath)+".json")
	err := os.Remove(path)
	if err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// ManifestFromDiscovery builds a Manifest from discovery + parsed file count.
func ManifestFromDiscovery(d *discovery.DiscoveryResult, fileCount int, commitSHA string) Manifest {
	langs := make(map[string]int)
	for lang, files := range d.Languages {
		langs[lang] = len(files)
	}
	now := time.Now().UTC()
	repoID := filepath.Base(d.Root)
	if repoID == "" || repoID == "." || repoID == "/" {
		repoID = "repo"
	}
	return Manifest{
		RepoID:      repoID,
		RepoRoot:    d.Root,
		Root:        d.Root,
		CommitSHA:   commitSHA,
		IndexedAt:   now,
		ScannedAt:   now,
		Languages:   langs,
		ModuleRoots: d.ModuleRoots,
		FileCount:   fileCount,
		Version:     "1",
	}
}

// ReadManifest loads manifest.json if present.
func ReadManifest(outDir string) (*Manifest, error) {
	path := filepath.Join(outDir, "manifest.json")
	data, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	var m Manifest
	if err := json.Unmarshal(data, &m); err != nil {
		return nil, err
	}
	return &m, nil
}

// SafePath converts a relative path into a filesystem-safe single filename.
func SafePath(rel string) string {
	rel = filepath.ToSlash(rel)
	rel = strings.ReplaceAll(rel, ":", "_")
	rel = strings.ReplaceAll(rel, "/", "__")
	rel = strings.ReplaceAll(rel, "\\", "__")
	return rel
}

func writeJSON(path string, v any) error {
	data, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	data = append(data, '\n')
	return os.WriteFile(path, data, 0o644)
}

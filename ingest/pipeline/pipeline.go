package pipeline

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/rantoinne/ncm/ingest/discovery"
	"github.com/rantoinne/ncm/ingest/git"
	"github.com/rantoinne/ncm/ingest/graph"
	"github.com/rantoinne/ncm/ingest/parser"
	"github.com/rantoinne/ncm/store/writer"
)

// Scan discovers languages, parses files, and writes file artifacts + manifest.
func Scan(ctx context.Context, repo, out string) error {
	repo, out, err := absPaths(repo, out)
	if err != nil {
		return err
	}
	disc, err := discovery.ScanAndDiscoverLanguages(repo)
	if err != nil {
		return fmt.Errorf("discovery: %w", err)
	}

	arts, err := parser.ParseAndExtract(ctx, disc.Root, disc.Languages)
	if err != nil {
		return fmt.Errorf("parse: %w", err)
	}

	if err := os.MkdirAll(filepath.Join(out, "files"), 0o755); err != nil {
		return err
	}
	// Clear stale file artifacts on full scan
	if entries, err := os.ReadDir(filepath.Join(out, "files")); err == nil {
		for _, e := range entries {
			_ = os.Remove(filepath.Join(out, "files", e.Name()))
		}
	}

	if err := writer.WriteFileArtifacts(out, arts); err != nil {
		return err
	}
	head, _ := git.HEADSHA(repo)
	if err := writer.WriteManifest(out, writer.ManifestFromDiscovery(disc, len(arts), head)); err != nil {
		return err
	}

	indexed := make(map[string]string, len(arts))
	for _, a := range arts {
		indexed[a.RelPath] = a.Hash
	}
	return writer.WriteCheckpoint(out, writer.Checkpoint{
		LastCommit:   head,
		IndexedFiles: indexed,
		UpdatedAt:    time.Now().UTC(),
	})
}

// Graph loads file artifacts from dataDir and writes graph.json to outDir.
func Graph(from, out string) error {
	from, out, err := absPaths(from, out)
	if err != nil {
		return err
	}
	arts, err := writer.LoadFileArtifacts(from)
	if err != nil {
		return err
	}
	repoID := "repo"
	if m, err := writer.ReadManifest(from); err == nil && m != nil && m.RepoID != "" {
		repoID = m.RepoID
	} else if m != nil && m.RepoRoot != "" {
		repoID = filepath.Base(m.RepoRoot)
	}
	g := graph.Build(arts, repoID)
	return writer.WriteGraph(out, g)
}

// Full runs scan + graph + git collection.
func Full(ctx context.Context, repo, out string) error {
	if err := Scan(ctx, repo, out); err != nil {
		return err
	}
	if err := Graph(out, out); err != nil {
		return err
	}
	ga, err := git.Collect(repo)
	if err != nil {
		return fmt.Errorf("git: %w", err)
	}
	return writer.WriteGit(out, ga)
}

// Incremental re-parses only files changed since the last checkpoint.
func Incremental(ctx context.Context, repo, out string) error {
	repo, out, err := absPaths(repo, out)
	if err != nil {
		return err
	}
	cp, err := writer.ReadCheckpoint(out)
	if err != nil {
		return err
	}
	if cp == nil || cp.LastCommit == "" {
		return Full(ctx, repo, out)
	}

	head, err := git.HEADSHA(repo)
	if err != nil {
		return err
	}
	if head == cp.LastCommit {
		return nil
	}

	changed, err := git.ChangedFilesSince(repo, cp.LastCommit)
	if err != nil {
		return err
	}
	if len(changed) == 0 {
		cp.LastCommit = head
		cp.UpdatedAt = time.Now().UTC()
		return writer.WriteCheckpoint(out, *cp)
	}

	// Map changed relative paths to languages
	langFiles := make(parser.LanguageFiles)
	for _, rel := range changed {
		abs := filepath.Join(repo, filepath.FromSlash(rel))
		info, err := os.Stat(abs)
		if err != nil {
			// deleted
			_ = writer.RemoveFileArtifact(out, rel)
			delete(cp.IndexedFiles, rel)
			continue
		}
		if info.IsDir() {
			continue
		}
		ext := filepath.Ext(abs)
		lang, ok := discovery.ExtToLanguage[ext]
		if !ok {
			continue
		}
		langFiles[lang] = append(langFiles[lang], abs)
	}

	if len(langFiles) > 0 {
		arts, err := parser.ParseAndExtract(ctx, repo, langFiles)
		if err != nil {
			return err
		}
		for _, art := range arts {
			if err := writer.WriteFileArtifact(out, art); err != nil {
				return err
			}
			cp.IndexedFiles[art.RelPath] = art.Hash
		}
	}

	// Rebuild graph from all artifacts
	if err := Graph(out, out); err != nil {
		return err
	}

	cp.LastCommit = head
	cp.UpdatedAt = time.Now().UTC()
	if err := writer.WriteCheckpoint(out, *cp); err != nil {
		return err
	}

	// Refresh discovery-based manifest lightly
	disc, err := discovery.ScanAndDiscoverLanguages(repo)
	if err == nil {
		_ = writer.WriteManifest(out, writer.ManifestFromDiscovery(disc, len(cp.IndexedFiles), head))
	}
	return nil
}

// Watch polls HEAD every interval and runs Incremental on changes.
func Watch(ctx context.Context, repo, out string, interval time.Duration) error {
	if interval <= 0 {
		interval = 5 * time.Second
	}
	repo, err := filepath.Abs(repo)
	if err != nil {
		return err
	}
	last, _ := git.HEADSHA(repo)
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	fmt.Fprintf(os.Stderr, "watching %s every %s\n", repo, interval)
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-ticker.C:
			head, err := git.HEADSHA(repo)
			if err != nil {
				fmt.Fprintf(os.Stderr, "watch: %v\n", err)
				continue
			}
			if head == last {
				continue
			}
			fmt.Fprintf(os.Stderr, "HEAD moved %s → %s; incremental index\n", short(last), short(head))
			if err := Incremental(ctx, repo, out); err != nil {
				fmt.Fprintf(os.Stderr, "incremental: %v\n", err)
				continue
			}
			last = head
		}
	}
}

func absPaths(repo, out string) (string, string, error) {
	r, err := filepath.Abs(repo)
	if err != nil {
		return "", "", err
	}
	o, err := filepath.Abs(out)
	if err != nil {
		return "", "", err
	}
	return r, o, nil
}

func short(sha string) string {
	if len(sha) > 8 {
		return sha[:8]
	}
	return sha
}

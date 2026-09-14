package pipeline

import (
	"context"
	"fmt"
	"log/slog"
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
	log := slog.Default().With("op", "scan")
	repo, out, err := absPaths(repo, out)
	if err != nil {
		return err
	}
	log.Info("discovering repository", "repo", repo, "out", out)

	disc, err := discovery.ScanAndDiscoverLanguages(repo)

	if err != nil {
		return fmt.Errorf("discovery: %w", err)
	}

	totalFiles := disc.Stats["files"]

	log.Info("discovery complete",
		"languages", len(disc.Languages),
		"files", totalFiles,
		"module_roots", len(disc.ModuleRoots),
	)

	log.Info("parsing files")

	arts, err := parser.ParseAndExtract(ctx, disc.Root, disc.Languages)

	if err != nil {
		return fmt.Errorf("parse: %w", err)
	}
	repoID := filepath.Base(disc.Root)
	head, _ := git.HEADSHA(repo)
	parser.StampStableIDs(arts, repoID, head)

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
	if err := writer.WriteManifest(out, writer.ManifestFromDiscovery(disc, len(arts), head)); err != nil {
		return err
	}

	indexed := make(map[string]string, len(arts))
	for _, a := range arts {
		indexed[a.RelPath] = a.Hash
	}
	if err := writer.WriteCheckpoint(out, writer.Checkpoint{
		LastCommit:   head,
		IndexedFiles: indexed,
		UpdatedAt:    time.Now().UTC(),
	}); err != nil {
		return err
	}
	log.Info("scan artifacts written", "out", out, "commit", short(head), "files", len(arts))
	return nil
}

// Graph loads file artifacts from dataDir and writes graph.json to outDir.
func Graph(from, out string) error {
	log := slog.Default().With("op", "graph")
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
	log.Info("building dependency graph", "files", len(arts), "repo_id", repoID)
	g := graph.Build(arts, repoID)
	if err := writer.WriteGraph(out, g); err != nil {
		return err
	}
	log.Info("graph written",
		"nodes", len(g.Nodes),
		"edges", len(g.Edges),
		"cycles", len(g.Cycles),
		"out", out,
	)
	return nil
}

// Full runs scan + graph + git collection.
func Full(ctx context.Context, repo, out string) error {
	log := slog.Default().With("op", "full")
	log.Info("full index starting", "repo", repo, "out", out)
	if err := Scan(ctx, repo, out); err != nil {
		return err
	}
	if err := Graph(out, out); err != nil {
		return err
	}
	log.Info("collecting git history", "repo", repo)
	ga, err := git.Collect(repo)
	if err != nil {
		return fmt.Errorf("git: %w", err)
	}
	if err := writer.WriteGit(out, ga); err != nil {
		return err
	}
	log.Info("git history written",
		"commits", len(ga.Commits),
		"files", len(ga.Files),
		"hotspots", len(ga.Hotspots),
		"edge_hints", len(ga.EdgeHints),
		"head", short(ga.HEAD),
	)
	return nil
}

// Incremental re-parses only files changed since the last checkpoint.
func Incremental(ctx context.Context, repo, out string) error {
	log := slog.Default().With("op", "incremental")
	repo, out, err := absPaths(repo, out)
	if err != nil {
		return err
	}
	cp, err := writer.ReadCheckpoint(out)
	if err != nil {
		return err
	}
	if cp == nil || cp.LastCommit == "" {
		log.Info("no checkpoint; running full index")
		return Full(ctx, repo, out)
	}

	head, err := git.HEADSHA(repo)
	if err != nil {
		return err
	}
	if head == cp.LastCommit {
		log.Info("already up to date", "commit", short(head))
		return nil
	}

	log.Info("delta detected", "from", short(cp.LastCommit), "to", short(head))
	changed, err := git.ChangedFilesSince(repo, cp.LastCommit)
	if err != nil {
		return err
	}
	if len(changed) == 0 {
		log.Info("no tracked source files changed; advancing checkpoint")
		cp.LastCommit = head
		cp.UpdatedAt = time.Now().UTC()
		return writer.WriteCheckpoint(out, *cp)
	}
	log.Info("re-parsing changed files", "changed", len(changed))

	// Map changed relative paths to languages
	langFiles := make(parser.LanguageFiles)
	for _, rel := range changed {
		abs := filepath.Join(repo, filepath.FromSlash(rel))
		info, err := os.Stat(abs)
		if err != nil {
			log.Debug("file removed", "path", rel)
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

	parsed := 0
	if len(langFiles) > 0 {
		arts, err := parser.ParseAndExtract(ctx, repo, langFiles)
		if err != nil {
			return err
		}
		parser.StampStableIDs(arts, filepath.Base(repo), head)
		for _, art := range arts {
			if err := writer.WriteFileArtifact(out, art); err != nil {
				return err
			}
			cp.IndexedFiles[art.RelPath] = art.Hash
		}
		parsed = len(arts)
	}
	log.Info("delta parse complete", "parsed", parsed)

	if err := Graph(out, out); err != nil {
		return err
	}

	log.Info("refreshing git history", "repo", repo)
	if ga, gerr := git.Collect(repo); gerr != nil {
		log.Warn("git refresh failed", "err", gerr)
	} else if err := writer.WriteGit(out, ga); err != nil {
		return err
	}

	cp.LastCommit = head
	cp.UpdatedAt = time.Now().UTC()
	if err := writer.WriteCheckpoint(out, *cp); err != nil {
		return err
	}

	disc, err := discovery.ScanAndDiscoverLanguages(repo)
	if err == nil {
		_ = writer.WriteManifest(out, writer.ManifestFromDiscovery(disc, len(cp.IndexedFiles), head))
	}
	log.Info("incremental complete", "commit", short(head), "indexed_files", len(cp.IndexedFiles))
	return nil
}

// Watch polls HEAD every interval and runs Incremental on changes.
func Watch(ctx context.Context, repo, out string, interval time.Duration) error {
	log := slog.Default().With("op", "watch")
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

	log.Info("watching for commits", "repo", repo, "interval", interval.String(), "head", short(last))
	for {
		select {
		case <-ctx.Done():
			log.Info("watch stopped", "reason", ctx.Err())
			return ctx.Err()
		case <-ticker.C:
			head, err := git.HEADSHA(repo)
			if err != nil {
				log.Warn("failed to read HEAD", "err", err)
				continue
			}
			if head == last {
				log.Debug("no change", "head", short(head))
				continue
			}
			log.Info("HEAD moved", "from", short(last), "to", short(head))
			if err := Incremental(ctx, repo, out); err != nil {
				log.Error("incremental failed", "err", err)
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

package ncmindex

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"time"

	"github.com/rantoinne/ncm/ingest/pipeline"
	"github.com/rantoinne/ncm/internal/logging"
)

// Run is the ncm-index CLI entrypoint (subcommand dispatch).
func Run(args []string) error {
	if len(args) < 1 {
		printUsage()
		return fmt.Errorf("subcommand required")
	}

	cmd := args[0]
	rest := args[1:]

	// Optional global flags before subcommand are not used; per-command --verbose supported via env.
	if cmd == "help" || cmd == "-h" || cmd == "--help" {
		printUsage()
		return nil
	}

	log := logging.With("cmd", cmd)
	start := time.Now()
	log.Info("starting", "args", rest)

	var err error
	switch cmd {
	case "scan":
		err = runScan(rest)
	case "graph":
		err = runGraph(rest)
	case "full":
		err = runFull(rest)
	case "incremental":
		err = runIncremental(rest)
	case "watch":
		err = runWatch(rest)
	default:
		printUsage()
		return fmt.Errorf("unknown subcommand: %s", cmd)
	}

	elapsed := time.Since(start)
	if err != nil {
		log.Error("failed", "elapsed", elapsed.String(), "err", err)
		return err
	}
	log.Info("completed", "elapsed", elapsed.String())
	return nil
}

func printUsage() {
	fmt.Fprintf(os.Stderr, `ncm-index — Neural Codebase Memory indexer

	Usage:
		ncm-index scan --repo PATH --out DIR
		ncm-index graph --from DIR --out DIR
		ncm-index full --repo PATH --out DIR
		ncm-index incremental --repo PATH --out DIR
		ncm-index watch --repo PATH --out DIR [--interval 5s]

	Logging:
		NCM_LOG_LEVEL=debug|info|warn|error
		NCM_LOG_FORMAT=text|json
		--verbose on any subcommand sets debug level
`)
}

func parseCommon(fs *flag.FlagSet, args []string) error {
	verbose := fs.Bool("verbose", false, "enable debug logging")
	if err := fs.Parse(args); err != nil {
		return err
	}
	if *verbose {
		logging.Setup(logging.Options{Level: slog.LevelDebug})
	}
	return nil
}

func runScan(args []string) error {
	fs := flag.NewFlagSet("scan", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := parseCommon(fs, args); err != nil {
		return err
	}
	return pipeline.Scan(context.Background(), *repo, *out)
}

func runGraph(args []string) error {
	fs := flag.NewFlagSet("graph", flag.ContinueOnError)
	from := fs.String("from", "./data", "directory with file artifacts")
	out := fs.String("out", "./data", "output directory")
	if err := parseCommon(fs, args); err != nil {
		return err
	}
	return pipeline.Graph(*from, *out)
}

func runFull(args []string) error {
	fs := flag.NewFlagSet("full", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := parseCommon(fs, args); err != nil {
		return err
	}
	return pipeline.Full(context.Background(), *repo, *out)
}

func runIncremental(args []string) error {
	fs := flag.NewFlagSet("incremental", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := parseCommon(fs, args); err != nil {
		return err
	}
	return pipeline.Incremental(context.Background(), *repo, *out)
}

func runWatch(args []string) error {
	fs := flag.NewFlagSet("watch", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	interval := fs.String("interval", "5s", "poll interval")
	if err := parseCommon(fs, args); err != nil {
		return err
	}
	d, err := time.ParseDuration(*interval)
	if err != nil {
		return fmt.Errorf("invalid --interval: %w", err)
	}
	return pipeline.Watch(context.Background(), *repo, *out, d)
}

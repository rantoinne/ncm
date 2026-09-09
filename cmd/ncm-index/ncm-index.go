package ncmindex

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	"github.com/rantoinne/ncm/ingest/pipeline"
)

// Run is the ncm-index CLI entrypoint (subcommand dispatch).
func Run(args []string) error {
	if len(args) < 1 {
		printUsage()
		return fmt.Errorf("subcommand required")
	}

	cmd := args[0]
	rest := args[1:]

	start := time.Now()
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
	case "help", "-h", "--help":
		printUsage()
		return nil
	default:
		printUsage()
		return fmt.Errorf("unknown subcommand: %s", cmd)
	}
	elapsed := time.Since(start)
	fmt.Fprintf(os.Stderr, "[ncm-index] %s took %s\n", cmd, elapsed)
	return err
}

func printUsage() {
	fmt.Fprintf(os.Stderr, `ncm-index — Neural Codebase Memory indexer

Usage:
  ncm-index scan --repo PATH --out DIR
  ncm-index graph --from DIR --out DIR
  ncm-index full --repo PATH --out DIR
  ncm-index incremental --repo PATH --out DIR
  ncm-index watch --repo PATH --out DIR [--interval 5s]
`)
}

func runScan(args []string) error {
	fs := flag.NewFlagSet("scan", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return pipeline.Scan(context.Background(), *repo, *out)
}

func runGraph(args []string) error {
	fs := flag.NewFlagSet("graph", flag.ContinueOnError)
	from := fs.String("from", "./data", "directory with file artifacts")
	out := fs.String("out", "./data", "output directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return pipeline.Graph(*from, *out)
}

func runFull(args []string) error {
	fs := flag.NewFlagSet("full", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return pipeline.Full(context.Background(), *repo, *out)
}

func runIncremental(args []string) error {
	fs := flag.NewFlagSet("incremental", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	if err := fs.Parse(args); err != nil {
		return err
	}
	return pipeline.Incremental(context.Background(), *repo, *out)
}

func runWatch(args []string) error {
	fs := flag.NewFlagSet("watch", flag.ContinueOnError)
	repo := fs.String("repo", ".", "repository path")
	out := fs.String("out", "./data", "output directory")
	interval := fs.String("interval", "5s", "poll interval")
	if err := fs.Parse(args); err != nil {
		return err
	}
	d, err := time.ParseDuration(*interval)
	if err != nil {
		return fmt.Errorf("invalid --interval: %w", err)
	}
	return pipeline.Watch(context.Background(), *repo, *out, d)
}

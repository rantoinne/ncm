package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"time"

	ncmindex "github.com/rantoinne/ncm/cmd/ncm-index"
	"github.com/rantoinne/ncm/ingest/parser"
)

func main() {
	pathParsed := flag.String("path", "", "path to the file")
	flag.Parse()

	path := *pathParsed

	if path == "" {
		fmt.Println("Path is required")
		os.Exit(1)
	}

	info, err := os.Stat(path)
	if err != nil {
		fmt.Println("Path does not exist")
		os.Exit(1)
	}

	if !info.IsDir() {
		fmt.Println("Path is a file, expected a directory!")
		os.Exit(1)
	}

	fmt.Println("Path is a directory, Scanning and discovering languages...")

	result, err := ncmindex.ScanAndDiscoverLanguages(path)
	if err != nil {
		fmt.Printf("Error scanning and discovering languages: %v\n", err)
		os.Exit(1)
	}

	startTime := time.Now()

	languageFiles := make(map[string][]string)
	for language, files := range result {
		languageFiles[language] = files
		fmt.Printf("Language: %s (%d files)\n", language, len(files))
	}

	ctx := context.Background()
	for resultv2 := range parser.ParseAll(ctx, languageFiles) {
		if resultv2.Err != nil {
			fmt.Fprintf(os.Stderr, "parse error %s: %v\n", resultv2.Path, resultv2.Err)
			continue
		}
		// walk result.Tree.RootNode(), extract symbols, etc.
		fmt.Printf("\nParsed tree for file %s:\n%s\n", resultv2.Path, resultv2.Tree.RootNode().String())
	}

	duration := time.Since(startTime)
	fmt.Printf("Time spent running: %v\n", duration)
}

package main

import (
	"flag"
	"fmt"
	"os"
	"time"

	ncmindex "github.com/rantoinne/ncm/cmd/ncm-index"
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
	for language, files := range result {
		fmt.Printf("Language: %s (%d files)\n", language, len(files))
	}
	duration := time.Since(startTime)
	fmt.Printf("Time spent running: %v\n", duration)
}

package ncmindex

import (
	"flag"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
)

var ignoreFiles = map[string]bool{
	".git":           true,
	".plans":         true,
	".vscode":        true,
	".idea":          true,
	".DS_Store":      true,
	".gitattributes": true,
	"node_modules":   true,
	"yarn_cache":     true,
	".gitignore":     true,
}

func Run() {
	pathFlag := flag.String("path", "", "path to the file")
	flag.Parse()

	root := *pathFlag

	if root == "" {
		fmt.Println("Path is required")
		os.Exit(1)
	}

	info, err := os.Stat(root)
	if err != nil {
		fmt.Println("Path does not exist")
		os.Exit(1)
	}

	if !info.IsDir() {
		fmt.Println("Path is a file, expected a directory")
		os.Exit(1)
	}

	fmt.Println("Path is a directory")

	counter := 0
	err = filepath.WalkDir(root, func(path string, data fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Directory
		if data.IsDir() {
			if ignoreFiles[data.Name()] {
				fmt.Printf("Ignoring directory: %s\n", path)
				return filepath.SkipDir
			}

			fmt.Printf("Directory: %s\n", path)
		}

		// File
		if !data.IsDir() {
			if ignoreFiles[data.Name()] {
				fmt.Printf("Ignoring file: %s\n", path)
				return nil
			}

			fmt.Printf("File: %s\n", path)
			counter++
		}

		return nil
	})

	if err != nil {
		fmt.Println("Error walking directory")
		os.Exit(1)
	}

	fmt.Printf("Total files: %d\n", counter)
}

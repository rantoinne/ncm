package ncmindex

import (
	"io/fs"
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

var extToLanguage = map[string]string{
	".go":   "go",
	".ts":   "typescript",
	".tsx":  "tsx",
	".js":   "javascript",
	".jsx":  "javascript",
	".py":   "python",
	".rs":   "rust",
	".java": "java",
	".rb":   "ruby",
	".c":    "c",
	".h":    "c",
	".cpp":  "cpp",
	".hpp":  "cpp",
	".php":  "php",
	".cs":   "c_sharp",
	".sh":   "bash",
}

type LanguageFiles map[string][]string

func ScanAndDiscoverLanguages(path string) (LanguageFiles, error) {
	result := make(LanguageFiles)

	err := filepath.WalkDir(path, func(path string, data fs.DirEntry, err error) error {
		if err != nil {
			return err
		}

		// Directory
		if data.IsDir() {
			if ignoreFiles[data.Name()] {
				return filepath.SkipDir
			}
			return nil
		}

		// File
		if ignoreFiles[data.Name()] {
			return nil
		}

		extension := filepath.Ext(data.Name())

		if language, ok := extToLanguage[extension]; ok {
			result[language] = append(result[language], path)
		}

		return nil
	})

	return result, err
}

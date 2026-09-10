package parser

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"os"
	"path/filepath"
	"runtime"
	"sync"

	sitter "github.com/smacker/go-tree-sitter"
)

// LanguageFiles maps language id → absolute file paths.
type LanguageFiles map[string][]string

// ParseResult is a raw tree-sitter parse outcome for one file.
type ParseResult struct {
	Path    string
	Lang    string
	Content []byte
	Tree    *sitter.Tree
	Err     error
}

// ParseAll fans out work per language with a bounded worker pool per language,
// reusing one parser instance per worker goroutine with the correct language set.
func ParseAll(ctx context.Context, langFiles LanguageFiles) <-chan ParseResult {
	out := make(chan ParseResult)
	var wg sync.WaitGroup
	numWorkers := runtime.NumCPU()
	if numWorkers < 1 {
		numWorkers = 1
	}

	for lang, files := range langFiles {
		files := files
		lang := lang
		langObj := GetLanguage(lang)
		wg.Add(1)
		go func() {
			defer wg.Done()
			if langObj == nil {
				for _, path := range files {
					select {
					case out <- ParseResult{Path: path, Lang: lang, Err: ErrUnsupportedLanguage(lang)}:
					case <-ctx.Done():
						return
					}
				}
				return
			}

			workerCh := make(chan string)
			var langWg sync.WaitGroup

			for i := 0; i < numWorkers; i++ {
				langWg.Add(1)
				go func() {
					defer langWg.Done()
					p := sitter.NewParser()
					p.SetLanguage(langObj)
					defer p.Close()

					for path := range workerCh {
						select {
						case <-ctx.Done():
							return
						default:
						}
						content, err := os.ReadFile(path)
						var tree *sitter.Tree
						if err == nil {
							tree, err = p.ParseCtx(ctx, nil, content)
						}
						select {
						case out <- ParseResult{
							Path:    path,
							Lang:    lang,
							Content: content,
							Tree:    tree,
							Err:     err,
						}:
						case <-ctx.Done():
							return
						}
					}
				}()
			}

			go func() {
				defer close(workerCh)
				for _, path := range files {
					select {
					case workerCh <- path:
					case <-ctx.Done():
						return
					}
				}
			}()

			langWg.Wait()
		}()
	}

	go func() {
		wg.Wait()
		close(out)
	}()

	return out
}

// ParseAndExtract parses all language files and returns FileArtifacts.
func ParseAndExtract(ctx context.Context, root string, langFiles LanguageFiles) ([]FileArtifact, error) {
	absRoot, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	var (
		mu   sync.Mutex
		arts []FileArtifact
	)
	for res := range ParseAll(ctx, langFiles) {
		if res.Err != nil {
			continue
		}
		rel, err := filepath.Rel(absRoot, res.Path)
		if err != nil {
			rel = res.Path
		}
		art := Extract(res.Path, rel, res.Lang, res.Tree, res.Content)
		sum := sha256.Sum256(res.Content)
		art.Hash = hex.EncodeToString(sum[:])
		if res.Tree != nil {
			res.Tree.Close()
		}
		mu.Lock()
		arts = append(arts, art)
		mu.Unlock()
	}
	return arts, nil
}

// UnsupportedLanguageError is returned when a language has no tree-sitter binding.
type UnsupportedLanguageError struct {
	Lang string
}

func (e UnsupportedLanguageError) Error() string {
	return "unsupported language: " + e.Lang
}

// ErrUnsupportedLanguage constructs an UnsupportedLanguageError.
func ErrUnsupportedLanguage(lang string) error {
	return UnsupportedLanguageError{Lang: lang}
}

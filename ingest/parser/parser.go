package parser

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"sync"

	sitter "github.com/smacker/go-tree-sitter"
)

// TODO: Export to types.go
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
// VERY EXPENSIVE TO RUN
func ParseAll(ctx context.Context, langFiles LanguageFiles) <-chan ParseResult {
	out := make(chan ParseResult)

	var wg sync.WaitGroup
	numWorkers := max(runtime.NumCPU(), 1)

	for lang, files := range langFiles {
		langObj := GetLanguage(lang)
		wg.Add(1)

		go func() {
			// fmt.Printf("Starting parsing for language: %s with %d files\n", lang, len(files))
			defer func() {
				// fmt.Printf("Finished parsing for language: %s\n", lang)
				wg.Done()
			}()
			// TODO: Can be optimised and not loop
			if langObj == nil {
				// fmt.Printf("Unsupported language encountered: %s\n", lang)
				for _, path := range files {
					// fmt.Printf("Emitting error for file %s (unsupported language: %s)\n", path, lang)
					select {
					case out <- ParseResult{Path: path, Lang: lang, Err: ErrUnsupportedLanguage(lang)}:
					case <-ctx.Done():
						// fmt.Printf("Context cancelled while emitting unsupported language error for %s\n", path)
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
					defer func() {
						// fmt.Printf("Worker %d for language %s done\n", i, lang)
						langWg.Done()
					}()

					// fmt.Printf("Worker %d for language %s starting\n", i, lang)
					p := sitter.NewParser()
					p.SetLanguage(langObj)
					defer p.Close()

					for path := range workerCh {
						// fmt.Printf("Worker %d for language %s parsing file: %s\n", i, lang, path)

						select {
						case <-ctx.Done():
							// fmt.Printf("Worker %d for lang %s: ctx cancelled while waiting on file: %s\n", i, lang, path)
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
							// fmt.Printf("Worker %d for lang %s emitted result for file: %s\n", i, lang, path)
						case <-ctx.Done():
							// fmt.Printf("Worker %d for lang %s: ctx cancelled while emitting result for file: %s\n", i, lang, path)
							return
						}
					}
				}()
			}

			// Feeder goroutine to feed the worker channel with files
			go func() {
				// fmt.Printf("Feeder for language %s starting\n", lang)
				defer func() {
					// fmt.Printf("Feeder for language %s finished, closing worker channel\n", lang)
					close(workerCh)
				}()
				for _, path := range files {
					select {
					case workerCh <- path:
						// fmt.Printf("Feeder for language %s sent file: %s to workerCh\n", lang, path)
					case <-ctx.Done():
						// fmt.Printf("Feeder for language %s: ctx cancelled, stopping\n", lang)
						return
					}
				}
			}()

			langWg.Wait()
			// fmt.Printf("All workers for language %s completed\n", lang)
		}()
	}

	go func() {
		wg.Wait()
		fmt.Println("Waiting for all workers to finish")
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

package parser

import (
	"context"
	"os"
	"runtime"
	"sync"

	sitter "github.com/smacker/go-tree-sitter"
	ts_sitter "github.com/smacker/go-tree-sitter/typescript/tsx"
	// tree_sitter_javascript "github.com/tree-sitter/tree-sitter-javascript/bindings/go"
)

type ParseResult struct {
	Path string
	Lang string
	Tree *sitter.Tree
	Err  error
}

type LanguageFiles map[string][]string

// ParseAll fans out work per language, with a bounded worker pool per language,
// reusing one parser instance per worker goroutine.
func ParseAll(ctx context.Context, langFiles LanguageFiles) <-chan ParseResult {
	out := make(chan ParseResult)

	var wg sync.WaitGroup

	// INSERT_YOUR_CODE

	numWorkers := runtime.NumCPU() // Define degree of parallelism

	for lang, files := range langFiles {
		files := files // capture range variable
		lang := lang   // capture range variable
		wg.Add(1)
		go func() {
			defer wg.Done()

			workerCh := make(chan string)
			var langWg sync.WaitGroup

			// Launch worker pool
			for i := 0; i < numWorkers; i++ {
				langWg.Add(1)
				go func() {
					defer langWg.Done()
					parser := sitter.NewParser()
					parser.SetLanguage(ts_sitter.GetLanguage())

					defer parser.Close()
					for path := range workerCh {
						select {
						case <-ctx.Done():
							return
						default:
						}
						content, err := os.ReadFile(path)
						var tree *sitter.Tree
						if err == nil {
							tree, err = parser.ParseCtx(ctx, nil, content)
						}
						select {
						case out <- ParseResult{
							Path: path,
							Lang: lang,
							Tree: tree,
							Err:  err,
						}:
						case <-ctx.Done():
							return
						}
					}
				}()
			}

			// Feed work to workers
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

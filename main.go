package main

import (
	"fmt"
	"os"

	ncmindex "github.com/rantoinne/ncm/cmd/ncm-index"
)

func main() {
	args := os.Args[1:]
	if err := ncmindex.Run(args); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

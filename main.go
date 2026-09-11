package main

import (
	"fmt"
	"os"

	ncmindex "github.com/rantoinne/ncm/cmd/ncm-index"
	"github.com/rantoinne/ncm/internal/logging"
)

func main() {
	logfile, err := os.OpenFile("app.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0644)
	if err != nil {
		fmt.Fprintf(os.Stderr, "error opening log file: %v\n", err)
		os.Exit(1)
	}
	defer logfile.Close()

	// os.Stdout = logfile
	// os.Stderr = logfile

	logging.Setup(logging.Options{})
	args := os.Args[1:]
	if err := ncmindex.Run(args); err != nil {
		fmt.Fprintf(os.Stderr, "error: %v\n", err)
		os.Exit(1)
	}
}

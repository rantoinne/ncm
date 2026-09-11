// Package logging configures structured slog logging for the NCM indexer.
package logging

import (
	"io"
	"log/slog"
	"os"
	"strings"
)

// Options control logger setup.
type Options struct {
	Level  slog.Level // default Info
	JSON   bool       // JSON to stderr when true; otherwise text
	Writer io.Writer  // defaults to os.Stderr
}

// Setup installs a process-wide default slog logger.
// Level may also be set via NCM_LOG_LEVEL (debug|info|warn|error).
func Setup(opts Options) *slog.Logger {
	if opts.Writer == nil {
		opts.Writer = os.Stderr
	}
	if env := strings.TrimSpace(os.Getenv("NCM_LOG_LEVEL")); env != "" {
		opts.Level = ParseLevel(env)
	}

	var handler slog.Handler
	hopts := &slog.HandlerOptions{Level: opts.Level}
	if opts.JSON || strings.EqualFold(os.Getenv("NCM_LOG_FORMAT"), "json") {
		handler = slog.NewJSONHandler(opts.Writer, hopts)
	} else {
		handler = slog.NewTextHandler(opts.Writer, hopts)
	}

	logger := slog.New(handler).With("component", "ncm-index")
	slog.SetDefault(logger)
	return logger
}

// ParseLevel maps a string to slog.Level (defaults to Info).
func ParseLevel(s string) slog.Level {
	switch strings.ToLower(strings.TrimSpace(s)) {
	case "debug", "dbg", "trace":
		return slog.LevelDebug
	case "warn", "warning":
		return slog.LevelWarn
	case "error", "err":
		return slog.LevelError
	default:
		return slog.LevelInfo
	}
}

// With returns a child logger with extra attrs (uses the default logger).
func With(args ...any) *slog.Logger {
	return slog.Default().With(args...)
}

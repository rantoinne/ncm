# NCM

**Neural Codebase Memory** — a Go CLI for ingesting, storing, and querying codebase context (files, structure, dependencies, and git history) to power explainable architectural Q&A.

## Current Status

Early scaffolding. The `ncm-index` command validates a directory path and walks its contents.

### What's implemented

- **Go module** — `github.com/rantoinne/ncm` (Go 1.23.2)
- **CLI entrypoint** — `main.go` delegates to `cmd/ncm-index`
- **Index command** — `ncm-index` with a `-path` flag for directory traversal
- **Directory walker** — recursively lists files and directories under a given root
- **Project layout** — placeholder packages for the planned architecture (see below)
- **Build** — `go build` at the repo root compiles to a local `ncm` binary (gitignored)

### Usage

```bash
go build -o ncm .
./ncm -path /path/to/project
```

Example output:

```
Path is a directory
Directory: /path/to/project
File: /path/to/project/main.go
...
```

## Project Plan

### Phase 1 — Foundation (in progress)

- [x] Initialize Go module and CLI skeleton
- [x] Add directory traversal with path validation
- [x] Scaffold package layout (`cmd`, `ingest`, `store`, `schema`, `brain`, `migrations`, `docs`)
- [x] Move CLI logic into `cmd/ncm-index`
- [ ] Define core data models in `schema/`
- [ ] Add structured logging and error handling

### Phase 2 — Ingestion

- [ ] Walk directories and extract file metadata (path, size, type, timestamps)
- [ ] Parse supported file types (Go, Python, TypeScript via tree-sitter)
- [ ] Build dependency graph (imports, calls, module boundaries)
- [ ] Add git history module (churn, ownership, renames)

### Phase 3 — Storage

- [ ] Choose and integrate a persistence layer (graph DB + shared artifacts)
- [ ] Write migrations in `migrations/`
- [ ] Implement CRUD operations in `store/`
- [ ] Index content for full-text and vector search

### Phase 4 — Brain (Query & Retrieval)

- [ ] Concept tagging and embedding clusters
- [ ] Knowledge graph traversal and evidence bundles
- [ ] Expose query API via CLI subcommands (`search`, `ask`, etc.)
- [ ] Python reasoning layer + FastAPI for explainable Q&A

### Phase 5 — Polish

- [ ] Configuration file support (`.ncm.yaml`)
- [ ] Incremental indexing with checkpoint/resume
- [ ] Documentation and examples in `docs/`
- [ ] E2E tests and CI

## Architecture

```
ncm/
├── main.go                  # Thin entrypoint; calls ncmindex.Run()
├── cmd/
│   └── ncm-index/           # Index CLI: full + incremental index
│       └── ncm-index.go
├── ingest/                  # Discovery, AST parsing, deps, git
├── store/                   # Persistence and indexing
├── schema/                  # Protobuf/JSON schemas shared by Go + Python
├── brain/                   # Semantics, reasoning, API (Python)
├── migrations/              # DB/graph schema migrations
└── docs/                    # User and developer documentation
```

## Recent Updates

| Date       | Change |
|------------|--------|
| 2026-07-09 | Initial commit — Go module, basic `-path` flag, directory walker |
| 2026-07-10 | Extended walker to print both files and directories; added `.gitignore` for binary |
| 2026-07-10 | Moved CLI logic to `cmd/ncm-index/ncm-index.go`; root `main.go` now delegates to `ncmindex.Run()` |

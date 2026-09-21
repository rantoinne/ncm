# Neural Codebase Memory (NCM)

Hybrid Go + Python system that indexes a repository into a knowledge graph and answers architectural questions with evidence.

## Architecture

- **Go (`ingest/`, `cmd/ncm-index`)** — discovery, tree-sitter parsing (Go/Python/TS/JS), dependency graph, git history, incremental indexing
- **Python (`brain/`)** — artifact loader, Neo4j/in-memory graph, concept tagging, reasoning, FastAPI
- **Shared** — JSON artifacts under `data/` (+ Protobuf schemas in `schema/`)

See **[docs/architecture.md](docs/architecture.md)** for diagrams of the stack (tree-sitter, Neo4j, Qdrant, FastAPI, …) and why each piece exists.

### Logging

```bash
NCM_LOG_LEVEL=debug ./ncm full --repo /path/to/repo --out ./data --verbose
NCM_LOG_LEVEL=debug PYTHONPATH=. python -m brain.ingest --data ./data --memory --verbose
# optional: NCM_LOG_FORMAT=json
```

## Quick start

```bash
# 1. Index a repo (Go)
go build -o ncm .
./ncm full --repo /path/to/repo --out ./data

# 2. Load into the brain (Python)
python3 -m venv .venv && source .venv/bin/activate
pip install -r brain/requirements.txt
PYTHONPATH=. python -m brain.ingest --data ./data --memory

# 3. Serve the API
PYTHONPATH=. uvicorn brain.api.main:app --reload --port 8000

# 4. Ask questions
curl -s localhost:8000/health
curl -s -X POST localhost:8000/v1/query \
  -H 'content-type: application/json' \
  -d '{"q":"Where does persistence live?"}'
```

Optional graph DB / vectors:

```bash
docker compose up -d   # Neo4j + Qdrant
# unset --memory / set NEO4J_URI=bolt://localhost:7687 NEO4J_USER=neo4j NEO4J_PASSWORD=ncmpassword
```

## CLI

```
./ncm scan --repo PATH --out DIR          # discover + parse → file artifacts
./ncm graph --from DIR --out DIR          # build dependency graph.json
./ncm full --repo PATH --out DIR          # scan + graph + git
./ncm incremental --repo PATH --out DIR   # delta re-index from checkpoint
./ncm watch --repo PATH --out DIR         # poll HEAD and incremental-index
```

## API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| POST | `/v1/query` | Natural-language Q&A with evidence (+ vector neighbors) |
| GET | `/v1/graph/path?from=&to=` | Shortest path |
| POST | `/v1/index` | Ingest artifacts; optional `run_go`/`mode=full|incremental` + `repo` |
| GET | `/v1/repo/{id}/map` | Repository map |
| GET | `/v1/repo/{id}/snapshot?commit=` | Time-slice scaffold |

Embeddings: hash by default; set `NCM_EMBED_BACKEND=sentence-transformers` for real models. Qdrant sync uses `QDRANT_URL` (default `http://localhost:6333`).

MCP tool loop: `PYTHONPATH=. python -m brain.mcp` (JSON lines on stdin).

## Layout

```
ncm/
├── cmd/ncm-index/       # Go CLI
├── ingest/              # discovery, parser, graph, git, pipeline
├── store/writer/        # artifact writer + checkpoint
├── brain/               # Python loader, graph, concepts, reasoning, API
├── schema/              # entities.proto, events.proto, entities.json
├── docker-compose.yml
└── .github/workflows/ci.yml
```

## Phase status

**Phase 1 MVP** — done.

**Phase 1.5** — largely implemented:

- [x] Embeddings pipeline (hash default; optional sentence-transformers) + Qdrant sync/search
- [x] Expanded concepts + embedding-cluster tags
- [x] Vector neighbors in reasoner evidence
- [x] Stable symbol IDs `{repo}:{commit}:{path}#{name}` when commit known
- [x] `EXTENDS` / `IMPLEMENTS` / `TESTS` edges; `REMOVED_IN` git hints
- [x] Git re-enabled on `full` + refresh on incremental
- [x] Architecture heuristics + safest-place / assumptions / likely-to-break intents
- [x] `POST /v1/index` can run Go indexer; merge mode; schema validation warnings
- [x] ADR/docs ingest, capsules, MCP tool server, Neo4j migration stub
- [x] Broader language *discovery* (Rust/Java/…); AST parse still Go/Python/TS/JS

**Phase 2/3** — scaffolds: snapshot API, docs graph, MCP, predict/compress modules (full GNN/runtime/cross-repo still future).

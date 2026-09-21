# Local development

## Index a repository

```bash
go build -o ncm .
./ncm full --repo /path/to/target --out ./data
# debug: NCM_LOG_LEVEL=debug ./ncm full --repo /path/to/target --out ./data --verbose
```

Artifacts written under `./data`:

- `manifest.json` — repo id, commit, language counts
- `files/*.json` — per-file symbols/imports
- `graph.json` — nodes/edges
- `git.json` — churn, ownership, temporal edge hints
- `checkpoint.json` — for incremental updates

## Load + query

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r brain/requirements.txt
PYTHONPATH=. python -m brain.ingest --data ./data --memory --verbose
PYTHONPATH=. uvicorn brain.api.main:app --reload --port 8000
```

Or: `bash cmd/ncm-serve/ncm-serve.sh`

## Docker services

```bash
docker compose up -d
export NEO4J_URI=bolt://localhost:7687
export NEO4J_USER=neo4j
export NEO4J_PASSWORD=ncmpassword
# optional vectors: QDRANT_URL=http://localhost:6333
# optional: NCM_EMBED_BACKEND=sentence-transformers
PYTHONPATH=. python -m brain.ingest --data ./data
```

## Index via API (triggers Go)

```bash
curl -s -X POST localhost:8000/v1/index \
  -H 'content-type: application/json' \
  -d '{"repo":".","data_dir":"./data","mode":"incremental","run_go":true,"merge":true}'
```

## Architecture diagrams

See [architecture.md](./architecture.md) for tech/stack diagrams (Go vs Python, tree-sitter, Neo4j, Qdrant, logging).

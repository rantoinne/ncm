# NCM Architecture & Technology Choices

This document explains **which technologies NCM uses**, **where they sit in the pipeline**, and **why they were chosen** for Phase 1.

## System overview

```mermaid
flowchart TB
    subgraph Target["Target repository"]
        Code[Source files]
        GitHist[Git history]
    end

    subgraph GoIngest["Go ingest layer — speed & static analysis"]
        Discovery[discovery<br/>walk + language detect]
        Parser[tree-sitter parser<br/>Go / Python / TS / JS]
        DepGraph[dependency graph<br/>IMPORTS / CALLS / DEPENDS_ON]
        GitMod[git module<br/>churn · ownership · renames]
        Pipeline[pipeline<br/>full / incremental / watch]
    end

    subgraph Artifacts["Shared artifact store — filesystem JSON"]
        Manifest[manifest.json]
        Files[files/*.json]
        GraphJSON[graph.json]
        GitJSON[git.json]
        Checkpoint[checkpoint.json]
        EmbedJSON[embeddings.json]
    end

    subgraph PyBrain["Python brain layer — semantics & Q&A"]
        Loader[artifact loader]
        Concepts[concept tagger]
        Embed[hash embeddings]
        Reason[intent + evidence reasoner]
        API[FastAPI /v1/*]
    end

    subgraph Stores["Persistent stores"]
        Neo4j[(Neo4j<br/>knowledge graph)]
        Mem[(In-memory graph<br/>local / tests)]
        Qdrant[(Qdrant<br/>vector index — Phase 1 scaffold)]
    end

    Code --> Discovery --> Parser --> DepGraph
    GitHist --> GitMod
    Discovery --> Pipeline
    Parser --> Pipeline
    DepGraph --> Pipeline
    GitMod --> Pipeline
    Pipeline --> Manifest & Files & GraphJSON & GitJSON & Checkpoint

    Manifest & Files & GraphJSON & GitJSON --> Loader
    Loader --> Concepts --> Neo4j
    Loader --> Embed --> EmbedJSON
    Loader --> Neo4j
    Loader -.-> Mem
    Embed -.-> Qdrant
    Neo4j --> Reason
    Mem --> Reason
    Reason --> API
```

## Why a hybrid Go + Python stack?

```mermaid
flowchart LR
    subgraph GoWhy["Go — ingest"]
        G1[Fast concurrent file walk]
        G2[Cheap CGO tree-sitter bindings]
        G3[Single static binary CLI]
        G4[Git CLI orchestration]
    end

    subgraph PyWhy["Python — brain"]
        P1[FastAPI + Pydantic DX]
        P2[Neo4j official driver]
        P3[NLP / embedding ecosystem]
        P4[LLM SDKs later]
    end

    GoWhy -->|"writes normalized JSON"| Contract[Shared artifact contract]
    Contract -->|"reads + enriches"| PyWhy
```

| Side | Responsibility | Why this language |
|------|----------------|-------------------|
| **Go** | Discover, parse AST, build structural graph, git history, incremental index | Throughput, easy CLI distribution, mature tree-sitter Go bindings |
| **Python** | Load artifacts, concept tags, graph queries, reasoning, HTTP API | Best ecosystem for Neo4j, embeddings, and LLM synthesis |

The boundary is deliberate: **Go never talks to Neo4j**; **Python never re-parses the whole tree**. They meet on disk via JSON (+ Protobuf schemas for the long-term contract).

---

## Technology map (what / where / why)

```mermaid
mindmap
  root((NCM Phase 1))
    Go ingest
      smacker/go-tree-sitter
        Multi-language AST
        Incremental-friendly
      stdlib log/slog
        Structured CLI logs
      os/exec git
        No heavy git library needed
      JSON artifacts
        Simple interop with Python
    Python brain
      FastAPI + Uvicorn
        Query / index HTTP API
      Pydantic
        Artifact validation
      neo4j driver
        Path queries · blast radius
      In-memory graph
        Zero-deps local demo
      Rule concept tagger
        No ML required day one
      Hash embeddings
        Deterministic stand-in for CodeBERT
    Infra
      Neo4j 5
        Native relationship queries
      Qdrant
        Vector search ready
      docker compose
        One-command local stack
```

### Detailed rationale

| Tech / lib | Layer | Role today | Why this choice | Alternatives considered |
|------------|-------|------------|-----------------|-------------------------|
| **Go 1.23** | Ingest CLI | Indexer binary | Fast concurrency, static binary | Rust (steeper), Node (slower AST) |
| **[tree-sitter](https://tree-sitter.github.io/)** via `smacker/go-tree-sitter` | Parser | Extract functions, imports, calls for Go/Python/TS/JS | Incremental, multi-language, battle-tested grammars | `go/ast` only (Go-only), Roslyn/ts-morph (polyglot pain) |
| **`log/slog`** | Go logging | Structured progress / errors | Stdlib since 1.21, JSON or text | zap/zerolog (extra deps for Phase 1) |
| **Git CLI (`os/exec`)** | History | Commits, churn, ownership, renames | Ubiquitous, rename detection with `-M` | go-git (heavier, rename quirks) |
| **Filesystem JSON** | Artifact store | Manifest, per-file AST, graph, git, checkpoint | Debuggable, language-agnostic | gRPC-only (harder to inspect), S3 later |
| **Protobuf schemas** (`schema/`) | Contract | Shared entity/event shapes | Forward-compatible Go↔Python IDL | JSON Schema alone (we keep both) |
| **Python 3.12+** | Brain | Semantics + API | Ecosystem fit | Stay Go-only (weaker LLM/embedding story) |
| **FastAPI + Uvicorn** | API | `/v1/query`, `/v1/index`, graph path | Async-friendly, OpenAPI free | Flask (less structure), gRPC (worse curl DX) |
| **Pydantic v2** | Validation | Artifact models | Matches FastAPI, catches schema drift | dataclasses (weaker validation) |
| **Neo4j 5** | Graph DB | CONTAINS / DEPENDS_ON / TAGGED_AS / OWNS paths | Native path queries + explainability | Kùzu (embedded alternative), Postgres recursive CTEs |
| **In-memory graph** | Graph DB fallback | Same query surface without Docker | Tests + laptop demos | Always require Neo4j (worse DX) |
| **Qdrant** | Vector DB | Scaffolded in compose; embeddings JSON today | Purpose-built ANN, simple Docker image | pgvector (needs Postgres), FAISS (ops heavier) |
| **Hash / feature embeddings** | Embeddings | Deterministic 64-d vectors → `embeddings.json` | No GPU / model download for Phase 1 | sentence-transformers / CodeBERT (next) |
| **Rule + import concept tagger** | Concepts | `auth`, `persistence`, `protocol`, … | Explainable, no training data | Pure LLM tagging (cost + hallucination) |
| **Template reasoner (+ optional OpenAI)** | Reasoning | Intent → graph evidence → answer | Evidence-first; LLM optional | LLM-only RAG (weaker architecture answers) |
| **docker compose** | Local ops | Neo4j + Qdrant | Matches Phase 1 “simple deploy” | k8s (overkill) |

---

## Data flow by concern

### 1. Parsing (tree-sitter)

```mermaid
sequenceDiagram
    participant CLI as ncm-index
    participant Disc as discovery
    participant TS as tree-sitter
    participant Out as data/files

    CLI->>Disc: walk repo (gitignore-aware)
    Disc-->>CLI: language → file list
    loop per language worker pool
        CLI->>TS: ParseCtx(source)
        TS-->>CLI: syntax tree
        CLI->>CLI: extract symbols / imports / calls
    end
    CLI->>Out: FileArtifact JSON
```

**Why tree-sitter?** One API for Go, Python, and TypeScript; error-tolerant on incomplete files; fast enough to re-parse only changed files on incremental runs.

### 2. Knowledge graph (Neo4j vs memory)

```mermaid
flowchart TB
    Artifacts[Go artifacts] --> Loader[Python loader]
    Loader --> Tag[Concept TAGGED_AS]
    Loader --> Struct[Structural edges]
    Tag --> StoreChoice{NEO4J_URI set<br/>and reachable?}
    Struct --> StoreChoice
    StoreChoice -->|yes| Neo4j[(Neo4j)]
    StoreChoice -->|no| Memory[(InMemoryGraphStore)]
    Neo4j --> Q[neighbors / shortest_path<br/>upstream / downstream / blast_radius]
    Memory --> Q
    Q --> Reasoner
```

**Why Neo4j?** Architectural questions are relationship questions (“what depends on X?”, “blast radius if Y deleted?”). Property graphs + Cypher path queries map cleanly to evidence bundles.

**Why keep in-memory?** Same interface for CI and `python -m brain.ingest --memory` without Docker.

### 3. Vectors (Qdrant — scaffold)

```mermaid
flowchart LR
    Sym[Functions / modules] --> Emb[Embedding pipeline]
    Emb -->|Phase 1| JSON[embeddings.json<br/>hash features]
    Emb -->|Next| Qdrant[(Qdrant)]
    Qdrant --> Reasoner[Semantic fallback<br/>when graph path empty]
```

**Why Qdrant in compose now?** Reserve the operational slot for concept/function similarity search without forcing model downloads on day one. Phase 1 already writes local embeddings so the contract exists.

### 4. Query path

```mermaid
flowchart LR
    Q[User question] --> Intent[IntentParser]
    Intent --> Plan[Graph query plan]
    Plan --> Traverse[Neo4j / memory traversal]
    Plan -.-> Vector[Vector search later]
    Traverse --> Evidence[Evidence bundle]
    Vector -.-> Evidence
    Evidence --> Synth[Template synthesizer<br/>optional LLM]
    Synth --> Ans[Explainable answer<br/>+ confidence + evidence]
```

---

## Logging

| Layer | Mechanism | Controls |
|-------|-----------|----------|
| Go indexer | `log/slog` via `internal/logging` | `NCM_LOG_LEVEL`, `NCM_LOG_FORMAT=json\|text`, `--verbose` |
| Python brain | stdlib `logging` via `brain.logging_config` | `NCM_LOG_LEVEL`, `NCM_LOG_FORMAT`, `--verbose` on ingest |

Example:

```bash
NCM_LOG_LEVEL=debug ./ncm full --repo ../redis-scratch-go --out ./data
NCM_LOG_LEVEL=debug PYTHONPATH=. python -m brain.ingest --data ./data --memory --verbose
```

---

## What is intentionally *not* in Phase 1

| Deferred | Reason |
|----------|--------|
| GNN coupling models | Needs mature graph + labels first |
| Runtime traces / logs | Separate telemetry ingest |
| Cross-repo org memory | Single-repo scope |
| Full CodeBERT / nomic embed in default path | Keep laptop-friendly; Qdrant ready when enabled |
| Always-on Neo4j requirement | In-memory fallback for DX |

---

## Quick mental model

> **Go turns a repo into facts.**  
> **Python turns facts into a graph and answers.**  
> **Neo4j stores relationships; Qdrant will store similarity; JSON is the bridge.**

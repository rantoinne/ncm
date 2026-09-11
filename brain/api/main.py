"""FastAPI reasoning API for Neural Codebase Memory."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from brain import __version__
from brain.concepts.tagger import concept_nodes, tag_artifacts, tags_to_edges
from brain.embeddings.pipeline import embed_file_artifacts
from brain.graph.store import InMemoryGraphStore, Neo4jGraphStore, create_store
from brain.loader.artifacts import load_all
from brain.logging_config import get_logger, setup_logging
from brain.reasoning.engine import Reasoner, path_between

load_dotenv()
setup_logging()
log = get_logger("ncm.api")

_store: InMemoryGraphStore | Neo4jGraphStore | None = None
_default_repo_id: str = ""


def get_store() -> InMemoryGraphStore | Neo4jGraphStore:
    global _store
    if _store is None:
        _store = create_store(prefer_neo4j=True)
        kind = "neo4j" if isinstance(_store, Neo4jGraphStore) else "memory"
        log.info("graph store ready kind=%s", kind)
    return _store


def set_store(store: InMemoryGraphStore | Neo4jGraphStore) -> None:
    global _store
    _store = store
    kind = "neo4j" if isinstance(store, Neo4jGraphStore) else "memory"
    log.info("graph store overridden kind=%s", kind)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    log.info("api starting version=%s", __version__)
    get_store()
    yield
    store = _store
    if store is not None:
        try:
            store.close()
            log.info("graph store closed")
        except Exception as exc:
            log.warning("error closing store: %s", exc)
    log.info("api shutdown")


app = FastAPI(
    title="Neural Codebase Memory",
    version=__version__,
    description="Explainable architectural Q&A over a code knowledge graph",
    lifespan=lifespan,
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - started) * 1000
    log.info(
        "%s %s -> %s (%.1fms)",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    return response


class QueryRequest(BaseModel):
    q: str = Field(..., min_length=1, description="Natural language question")
    repo_id: str | None = None


class IndexRequest(BaseModel):
    data_dir: str = "./data"


def _ingest_bundle(data_dir: str) -> dict[str, Any]:
    global _default_repo_id
    log.info("ingest starting data_dir=%s", data_dir)
    bundle = load_all(data_dir)
    repo_id = bundle.manifest.repo_id
    _default_repo_id = repo_id
    log.info(
        "artifacts loaded repo_id=%s files=%s graph_nodes=%s graph_edges=%s commit=%s",
        repo_id,
        len(bundle.files),
        len(bundle.graph.nodes),
        len(bundle.graph.edges),
        bundle.manifest.commit_sha[:12] if bundle.manifest.commit_sha else "",
    )
    store = get_store()
    store.clear_repo(repo_id)

    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    # Repository node
    nodes.append(
        {
            "id": f"repo:{repo_id}",
            "type": "Repository",
            "label": repo_id,
            "props": {
                "repo_id": repo_id,
                "root": bundle.manifest.root,
                "commit_sha": bundle.manifest.commit_sha,
                "file_count": bundle.manifest.file_count,
            },
        }
    )

    # Structural graph from Go
    for n in bundle.graph.nodes:
        props = dict(n.props)
        props["repo_id"] = repo_id
        nodes.append({"id": n.id, "type": n.type, "label": n.label or n.id, "props": props})
    for e in bundle.graph.edges:
        edges.append(
            {
                "id": e.id,
                "type": e.type,
                "from": e.from_id,
                "to": e.to,
                "confidence": e.confidence,
                "evidence": e.evidence,
            }
        )

    # File / symbol nodes from artifacts (fill gaps). IDs match Go graph (rel path).
    seen_ids = {n["id"] for n in nodes}
    for art in bundle.files:
        fid = art.file_id or art.path
        if fid not in seen_ids:
            nodes.append(
                {
                    "id": fid,
                    "type": "File",
                    "label": fid.split("/")[-1],
                    "props": {
                        "repo_id": repo_id,
                        "path": fid,
                        "language": art.language,
                        "package": art.package,
                    },
                }
            )
            seen_ids.add(fid)
        for sym in art.symbols:
            sid = sym.id or f"{fid}#{sym.name}"
            if sid not in seen_ids:
                nodes.append(
                    {
                        "id": sid,
                        "type": (sym.kind or "function").capitalize(),
                        "label": sym.name,
                        "props": {
                            "repo_id": repo_id,
                            "path": fid,
                            "file_path": fid,
                            "signature": sym.signature,
                            "start_line": sym.start_line,
                            "end_line": sym.end_line,
                        },
                    }
                )
                seen_ids.add(sid)
                edges.append(
                    {
                        "id": f"{fid}-CONTAINS-{sid}",
                        "type": "CONTAINS",
                        "from": fid,
                        "to": sid,
                        "confidence": 1.0,
                        "evidence": ["file_artifact"],
                    }
                )

    # Git metadata
    for gf in bundle.git.files:
        fid = gf.path
        for n in nodes:
            if n["id"] == fid or (n.get("props") or {}).get("path") == gf.path:
                n.setdefault("props", {})
                n["props"]["churn"] = gf.churn
                n["props"]["commits"] = gf.commits
                n["props"]["path"] = gf.path
                n["props"]["repo_id"] = repo_id
                if gf.owner:
                    n["props"]["owner"] = gf.owner
                break
        else:
            nodes.append(
                {
                    "id": fid,
                    "type": "File",
                    "label": gf.path.split("/")[-1],
                    "props": {
                        "repo_id": repo_id,
                        "path": gf.path,
                        "churn": gf.churn,
                        "commits": gf.commits,
                        "owner": gf.owner,
                    },
                }
            )
            seen_ids.add(fid)

    for commit in bundle.git.commits:
        cid = f"commit:{commit.sha}"
        if cid not in seen_ids:
            nodes.append(
                {
                    "id": cid,
                    "type": "Commit",
                    "label": commit.sha[:12],
                    "props": {
                        "repo_id": repo_id,
                        "sha": commit.sha,
                        "message": commit.message,
                        "author": commit.author,
                        "date": commit.date,
                    },
                }
            )
            seen_ids.add(cid)

    for hint in bundle.git.edge_hints:
        if not hint.from_id or not hint.to:
            continue
        src, dst = hint.from_id, hint.to
        if hint.type == "INTRODUCED_IN":
            if not dst.startswith("commit:"):
                dst = f"commit:{dst}"
        elif hint.type == "MODIFIED_BY":
            if not dst.startswith("author:"):
                dst = f"author:{dst}"
            if dst not in seen_ids:
                nodes.append(
                    {
                        "id": dst,
                        "type": "Author",
                        "label": hint.to,
                        "props": {"repo_id": repo_id, "name": hint.to},
                    }
                )
                seen_ids.add(dst)
        elif hint.type == "OWNS":
            if not src.startswith("author:"):
                src = f"author:{src}"
            if src not in seen_ids:
                nodes.append(
                    {
                        "id": src,
                        "type": "Author",
                        "label": hint.from_id,
                        "props": {"repo_id": repo_id, "name": hint.from_id},
                    }
                )
                seen_ids.add(src)
        edges.append(
            {
                "id": f"{hint.type}:{src}->{dst}",
                "type": hint.type,
                "from": src,
                "to": dst,
                "confidence": hint.confidence,
                "evidence": hint.evidence,
            }
        )

    for own in bundle.git.ownership:
        author_id = f"author:{own.owner}"
        if author_id not in seen_ids:
            nodes.append(
                {
                    "id": author_id,
                    "type": "Author",
                    "label": own.owner,
                    "props": {"repo_id": repo_id, "name": own.owner},
                }
            )
            seen_ids.add(author_id)
        fid = own.path
        edges.append(
            {
                "id": f"{author_id}-OWNS-{fid}",
                "type": "OWNS",
                "from": author_id,
                "to": fid,
                "confidence": own.confidence,
                "evidence": ["git_ownership"],
            }
        )
        for n in nodes:
            if n["id"] == fid:
                n.setdefault("props", {})
                n["props"]["owner"] = own.owner
                n["props"]["ownership_confidence"] = own.confidence
                break

    for ren in bundle.git.renames:
        edges.append(
            {
                "id": f"rename:{ren.from_path}->{ren.to}:{ren.sha}",
                "type": "RENAMED_TO",
                "from": ren.from_path,
                "to": ren.to,
                "confidence": 1.0,
                "evidence": [f"sha:{ren.sha}"] if ren.sha else [],
            }
        )

    # Concept tagging
    tags = tag_artifacts(bundle.files)
    nodes.extend(concept_nodes(tags, repo_id=repo_id))
    edges.extend(tags_to_edges(tags))
    log.info("concept tagging complete tags=%s", len(tags))

    # Embeddings (hash features)
    emb_path = Path(data_dir) / "embeddings.json"
    embed_file_artifacts(bundle.files, emb_path)
    log.debug("embeddings written path=%s", emb_path)

    n_count = store.ingest_nodes(nodes, repo_id=repo_id)
    e_count = store.ingest_edges(edges, repo_id=repo_id)
    log.info(
        "ingest complete repo_id=%s nodes=%s edges=%s concepts=%s",
        repo_id,
        n_count,
        e_count,
        len(tags),
    )

    return {
        "repo_id": repo_id,
        "nodes_ingested": n_count,
        "edges_ingested": e_count,
        "files": len(bundle.files),
        "concepts_tagged": len(tags),
        "embeddings_path": str(emb_path),
        "commit_sha": bundle.manifest.commit_sha,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    store = get_store()
    kind = "neo4j" if isinstance(store, Neo4jGraphStore) else "memory"
    return {"status": "ok", "version": __version__, "store": kind}


@app.post("/v1/query")
def query(body: QueryRequest) -> dict[str, Any]:
    store = get_store()
    rid = body.repo_id or _default_repo_id or os.getenv("NCM_REPO_ID", "")
    log.info("query repo_id=%s q=%r", rid, body.q[:200])
    reasoner = Reasoner(store, repo_id=rid)
    result = reasoner.answer(body.q, repo_id=rid or None)
    payload = result.to_dict()
    log.info(
        "query answered confidence=%.2f evidence=%s",
        float(payload.get("confidence") or 0),
        len(payload.get("evidence") or []),
    )
    return payload


@app.get("/v1/graph/path")
def graph_path(
    from_id: str = Query(..., alias="from"),
    to_id: str = Query(..., alias="to"),
) -> dict[str, Any]:
    store = get_store()
    log.debug("path query from=%s to=%s", from_id, to_id)
    result = path_between(store, from_id, to_id)
    if not result["path"]:
        raise HTTPException(status_code=404, detail=f"No path between {from_id} and {to_id}")
    return result


@app.post("/v1/index")
def index_repo(body: IndexRequest) -> dict[str, Any]:
    data_dir = Path(body.data_dir)
    if not data_dir.exists():
        raise HTTPException(status_code=400, detail=f"data_dir not found: {data_dir}")
    try:
        return _ingest_bundle(str(data_dir))
    except FileNotFoundError as exc:
        log.warning("index missing data: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.exception("index failed")
        raise HTTPException(status_code=500, detail=f"index failed: {exc}") from exc


@app.get("/v1/repo/{repo_id}/map")
def repo_map(repo_id: str) -> dict[str, Any]:
    store = get_store()
    log.debug("repo map repo_id=%s", repo_id)
    return store.get_repo_map(repo_id)

"""Embedding pipeline: hash features by default; optional sentence-transformers."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any

EMBED_DIM = int(os.getenv("NCM_EMBED_DIM", "64"))
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[0-9]+")

_st_model: Any = None
_st_failed = False


def _backend() -> str:
    """hash | sentence-transformers (via NCM_EMBED_BACKEND)."""
    return (os.getenv("NCM_EMBED_BACKEND") or "hash").strip().lower()


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _hash_to_index(token: str, dim: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dim


def _hash_sign(token: str) -> float:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return 1.0 if digest[0] % 2 == 0 else -1.0


def _embed_hash(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        seed = hashlib.sha256((text or "").encode("utf-8")).digest()
        for i in range(dim):
            vec[i] = ((seed[i % len(seed)] / 255.0) * 2.0 - 1.0) * 0.01
        return vec

    for tok in tokens:
        idx = _hash_to_index(tok, dim)
        vec[idx] += _hash_sign(tok)
        for n in (2, 3):
            if len(tok) < n:
                continue
            for i in range(len(tok) - n + 1):
                gram = tok[i : i + n]
                gidx = _hash_to_index(f"ng:{gram}", dim)
                vec[gidx] += 0.5 * _hash_sign(f"ng:{gram}")

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _get_st_model() -> Any | None:
    global _st_model, _st_failed
    if _st_failed:
        return None
    if _st_model is not None:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer

        name = os.getenv("NCM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        _st_model = SentenceTransformer(name)
        return _st_model
    except Exception:
        _st_failed = True
        return None


def embed_text(text: str, dim: int | None = None) -> list[float]:
    """Embed a single string. Uses ST when NCM_EMBED_BACKEND=sentence-transformers."""
    dim = dim or EMBED_DIM
    if _backend() in ("sentence-transformers", "st", "sbert"):
        model = _get_st_model()
        if model is not None:
            vec = model.encode([text or ""], normalize_embeddings=True)[0]
            return [float(x) for x in vec]
    return _embed_hash(text, dim)


def embed_texts(texts: list[str], dim: int | None = None) -> list[list[float]]:
    dim = dim or EMBED_DIM
    if _backend() in ("sentence-transformers", "st", "sbert"):
        model = _get_st_model()
        if model is not None:
            vecs = model.encode(texts or [""], normalize_embeddings=True, batch_size=64)
            return [[float(x) for x in v] for v in vecs]
    return [_embed_hash(t, dim) for t in texts]


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def search_local(
    query: str,
    embeddings: dict[str, list[float]],
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Brute-force cosine search over a local id→vector map."""
    if not embeddings:
        return []
    q = embed_text(query, dim=len(next(iter(embeddings.values()))))
    scored = []
    for nid, vec in embeddings.items():
        scored.append({"id": nid, "score": cosine(q, vec)})
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]


def store_embeddings(
    items: dict[str, list[float]] | list[dict[str, Any]],
    path: str | Path,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any]
    if isinstance(items, dict):
        dim = len(next(iter(items.values()))) if items else EMBED_DIM
        payload = {
            "dim": dim,
            "backend": _backend(),
            "count": len(items),
            "embeddings": {k: list(v) for k, v in items.items()},
        }
    else:
        embeddings: dict[str, list[float]] = {}
        meta: dict[str, Any] = {}
        for item in items:
            eid = str(item["id"])
            embeddings[eid] = list(item["vector"])
            if "text" in item:
                meta[eid] = {"text": item["text"]}
        dim = len(next(iter(embeddings.values()))) if embeddings else EMBED_DIM
        payload = {
            "dim": dim,
            "backend": _backend(),
            "count": len(embeddings),
            "embeddings": embeddings,
            "meta": meta,
        }

    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            old = existing.get("embeddings") or {}
            old.update(payload["embeddings"])
            payload["embeddings"] = old
            payload["count"] = len(old)
            if "meta" in payload or "meta" in existing:
                merged_meta = dict(existing.get("meta") or {})
                merged_meta.update(payload.get("meta") or {})
                payload["meta"] = merged_meta
        except (json.JSONDecodeError, OSError):
            pass

    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_embeddings(path: str | Path) -> dict[str, list[float]]:
    path = Path(path)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = data.get("embeddings") or {}
    return {k: list(v) for k, v in raw.items()}


def remove_embeddings(path: str | Path, ids: list[str]) -> None:
    """Tombstone: drop ids from embeddings.json."""
    path = Path(path)
    if not path.exists() or not ids:
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return
    emb = data.get("embeddings") or {}
    meta = data.get("meta") or {}
    for i in ids:
        emb.pop(i, None)
        meta.pop(i, None)
    data["embeddings"] = emb
    data["meta"] = meta
    data["count"] = len(emb)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def embed_file_artifacts(
    files: list[Any],
    out_path: str | Path,
    *,
    only_ids: set[str] | None = None,
    sync_qdrant: bool = True,
    repo_id: str = "",
) -> dict[str, list[float]]:
    """Embed file paths + symbol signatures and store under out_path."""
    texts: list[str] = []
    ids: list[str] = []
    text_by_id: dict[str, str] = {}
    for art in files:
        path = getattr(art, "file_id", None) or getattr(art, "rel_path", None) or getattr(art, "path", "") or ""
        package = getattr(art, "package", "") or ""
        imports = " ".join(getattr(art, "imports", []) or [])
        fid = path
        if only_ids is None or fid in only_ids:
            ids.append(fid)
            t = f"{path} {package} {imports}"
            texts.append(t)
            text_by_id[fid] = t
        for sym in getattr(art, "symbols", []) or []:
            sid = getattr(sym, "id", None) or f"{path}#{getattr(sym, 'name', '')}"
            if only_ids is not None and sid not in only_ids:
                continue
            ids.append(sid)
            t = f"{getattr(sym, 'name', '')} {getattr(sym, 'signature', '')} {getattr(sym, 'kind', '')}"
            texts.append(t)
            text_by_id[sid] = t
    vectors = embed_texts(texts) if texts else []
    mapping = {i: v for i, v in zip(ids, vectors)}
    store_embeddings(mapping, out_path)
    if sync_qdrant and mapping:
        try:
            from brain.embeddings.qdrant_client import sync_embeddings_to_qdrant

            sync_embeddings_to_qdrant(mapping, repo_id=repo_id, texts=text_by_id)
        except Exception:
            pass
    return mapping

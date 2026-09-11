"""Deterministic hash-feature embeddings (no heavy ML deps)."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

EMBED_DIM = 64

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{1,}|[0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _hash_to_index(token: str, dim: int) -> int:
    digest = hashlib.sha256(token.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big") % dim


def _hash_sign(token: str) -> float:
    digest = hashlib.md5(token.encode("utf-8")).digest()
    return 1.0 if digest[0] % 2 == 0 else -1.0


def embed_text(text: str, dim: int = EMBED_DIM) -> list[float]:
    """Embed a single string into a fixed-dim float vector via hashing tricks."""
    vec = [0.0] * dim
    tokens = _tokenize(text)
    if not tokens:
        # Empty text still gets a tiny deterministic bias from content hash
        seed = hashlib.sha256((text or "").encode("utf-8")).digest()
        for i in range(dim):
            vec[i] = ((seed[i % len(seed)] / 255.0) * 2.0 - 1.0) * 0.01
        return vec

    for tok in tokens:
        idx = _hash_to_index(tok, dim)
        vec[idx] += _hash_sign(tok)
        # Character n-grams for robustness
        for n in (2, 3):
            if len(tok) < n:
                continue
            for i in range(len(tok) - n + 1):
                gram = tok[i : i + n]
                gidx = _hash_to_index(f"ng:{gram}", dim)
                vec[gidx] += 0.5 * _hash_sign(f"ng:{gram}")

    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed_texts(texts: list[str], dim: int = EMBED_DIM) -> list[list[float]]:
    """Embed a batch of texts into fixed-dim (default 64) vectors."""
    return [embed_text(t, dim=dim) for t in texts]


def store_embeddings(
    items: dict[str, list[float]] | list[dict[str, Any]],
    path: str | Path,
) -> Path:
    """
    Persist embeddings to a local JSON file (default layout: data/embeddings.json).

    `items` may be {id: vector} or a list of {id, vector, text?} dicts.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    payload: dict[str, Any]
    if isinstance(items, dict):
        payload = {
            "dim": EMBED_DIM,
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
        payload = {
            "dim": EMBED_DIM,
            "count": len(embeddings),
            "embeddings": embeddings,
            "meta": meta,
        }

    # Merge with existing file if present
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


def embed_file_artifacts(
    files: list[Any],
    out_path: str | Path,
) -> dict[str, list[float]]:
    """Embed file paths + symbol signatures and store under out_path."""
    texts: list[str] = []
    ids: list[str] = []
    for art in files:
        path = getattr(art, "file_id", None) or getattr(art, "rel_path", None) or getattr(art, "path", "") or ""
        package = getattr(art, "package", "") or ""
        imports = " ".join(getattr(art, "imports", []) or [])
        fid = path
        ids.append(fid)
        texts.append(f"{path} {package} {imports}")
        for sym in getattr(art, "symbols", []) or []:
            sid = getattr(sym, "id", None) or f"{path}#{getattr(sym, 'name', '')}"
            ids.append(sid)
            texts.append(
                f"{getattr(sym, 'name', '')} {getattr(sym, 'signature', '')} {getattr(sym, 'kind', '')}"
            )
    vectors = embed_texts(texts)
    mapping = {i: v for i, v in zip(ids, vectors)}
    store_embeddings(mapping, out_path)
    return mapping

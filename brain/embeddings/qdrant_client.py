"""Thin Qdrant client for NCM embeddings (optional; falls back if unreachable)."""

from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
DEFAULT_COLLECTION = os.getenv("NCM_QDRANT_COLLECTION", "ncm_embeddings")


class QdrantStore:
    """HTTP client for upsert/search against a Qdrant collection."""

    def __init__(
        self,
        url: str | None = None,
        collection: str | None = None,
        timeout: float = 5.0,
    ) -> None:
        self.url = (url or DEFAULT_URL).rstrip("/")
        self.collection = collection or DEFAULT_COLLECTION
        self.timeout = timeout
        self._available: bool | None = None

    def available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            r = httpx.get(f"{self.url}/collections", timeout=self.timeout)
            self._available = r.status_code == 200
        except Exception:
            self._available = False
        return self._available

    def ensure_collection(self, dim: int) -> bool:
        if not self.available():
            return False
        try:
            r = httpx.get(f"{self.url}/collections/{self.collection}", timeout=self.timeout)
            if r.status_code == 200:
                return True
            payload = {
                "vectors": {"size": dim, "distance": "Cosine"},
            }
            cr = httpx.put(
                f"{self.url}/collections/{self.collection}",
                json=payload,
                timeout=self.timeout,
            )
            return cr.status_code in (200, 201)
        except Exception:
            self._available = False
            return False

    def upsert(
        self,
        points: list[dict[str, Any]],
        dim: int,
    ) -> int:
        """
        Upsert points: each {id: str|int, vector: list[float], payload?: dict}.
        Returns number upserted, or 0 on failure.
        """
        if not points or not self.ensure_collection(dim):
            return 0
        body_points = []
        for i, p in enumerate(points):
            pid = p.get("id")
            # Qdrant accepts UUID or unsigned int; hash string ids to int.
            if isinstance(pid, str):
                point_id = abs(hash(pid)) % (2**63 - 1)
            else:
                point_id = int(pid) if pid is not None else i
            body_points.append(
                {
                    "id": point_id,
                    "vector": list(p["vector"]),
                    "payload": {
                        **(p.get("payload") or {}),
                        "node_id": str(p.get("id", "")),
                    },
                }
            )
        try:
            r = httpx.put(
                f"{self.url}/collections/{self.collection}/points",
                params={"wait": "true"},
                json={"points": body_points},
                timeout=max(self.timeout, 30.0),
            )
            if r.status_code not in (200, 201):
                return 0
            return len(body_points)
        except Exception:
            self._available = False
            return 0

    def search(
        self,
        vector: list[float],
        limit: int = 10,
        repo_id: str = "",
    ) -> list[dict[str, Any]]:
        if not self.available():
            return []
        filt: dict[str, Any] | None = None
        if repo_id:
            filt = {
                "must": [{"key": "repo_id", "match": {"value": repo_id}}],
            }
        body: dict[str, Any] = {
            "vector": vector,
            "limit": limit,
            "with_payload": True,
        }
        if filt:
            body["filter"] = filt
        try:
            r = httpx.post(
                f"{self.url}/collections/{self.collection}/points/search",
                json=body,
                timeout=self.timeout,
            )
            if r.status_code != 200:
                return []
            hits = []
            for h in r.json().get("result") or []:
                payload = h.get("payload") or {}
                hits.append(
                    {
                        "id": payload.get("node_id") or str(h.get("id")),
                        "score": float(h.get("score") or 0),
                        "payload": payload,
                    }
                )
            return hits
        except Exception:
            return []


def sync_embeddings_to_qdrant(
    embeddings: dict[str, list[float]],
    repo_id: str = "",
    texts: dict[str, str] | None = None,
) -> int:
    """Upsert id→vector map into Qdrant. Returns count or 0 if Qdrant down."""
    if not embeddings:
        return 0
    dim = len(next(iter(embeddings.values())))
    store = QdrantStore()
    points = []
    for nid, vec in embeddings.items():
        points.append(
            {
                "id": nid,
                "vector": vec,
                "payload": {
                    "repo_id": repo_id,
                    "text": (texts or {}).get(nid, ""),
                },
            }
        )
    # Batch in chunks of 256
    total = 0
    for i in range(0, len(points), 256):
        total += store.upsert(points[i : i + 256], dim=dim)
    return total

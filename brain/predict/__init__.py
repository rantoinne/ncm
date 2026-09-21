"""Lightweight prediction stubs (Phase 3 scaffold)."""

from __future__ import annotations

from typing import Any


def predict_likely_break(
    hotspots: list[dict[str, Any]],
    blast_by_id: dict[str, dict[str, Any]] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Rank files by churn × optional blast-radius size."""
    scored: list[dict[str, Any]] = []
    for h in hotspots:
        path = str(h.get("path") or h.get("id") or h.get("label") or "")
        churn = float(h.get("commit_count") or h.get("commits") or h.get("churn") or 0)
        blast = 1.0
        if blast_by_id and path in blast_by_id:
            blast = float(blast_by_id[path].get("count") or len(blast_by_id[path].get("nodes") or []) or 1)
        scored.append(
            {
                "path": path,
                "score": round(churn * (1.0 + 0.1 * blast), 3),
                "churn": churn,
                "blast": blast,
            }
        )
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:limit]

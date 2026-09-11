"""Format graph paths and evidence bundles for API responses."""

from __future__ import annotations

from typing import Any


def format_path(nodes: list[dict[str, Any]]) -> str:
    """Render a node path as a human-readable arrow chain."""
    if not nodes:
        return "(empty path)"
    parts: list[str] = []
    for n in nodes:
        label = n.get("label") or n.get("id") or "?"
        ntype = n.get("type")
        if ntype:
            parts.append(f"{ntype}:{label}")
        else:
            parts.append(str(label))
    return " → ".join(parts)


def format_evidence(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize a single evidence item for API output."""
    etype = str(item.get("type") or "unknown")
    out: dict[str, Any] = {"type": etype}

    if etype == "graph_path":
        nodes = item.get("nodes") or []
        out["nodes"] = nodes
        out["formatted"] = item.get("formatted") or format_path(nodes)
        out["length"] = item.get("length", max(0, len(nodes) - 1))
        return out

    if etype == "commit":
        out["sha"] = item.get("sha") or item.get("id")
        out["message"] = item.get("message") or item.get("label")
        if item.get("props"):
            props = item["props"]
            out["sha"] = out["sha"] or props.get("sha")
            out["message"] = out["message"] or props.get("message")
            out["author"] = props.get("author")
            out["date"] = props.get("date")
        return out

    if etype == "concept_match":
        out["concept"] = item.get("concept")
        out["node_id"] = item.get("node_id") or item.get("id")
        out["label"] = item.get("label")
        out["confidence"] = item.get("confidence")
        if item.get("evidence"):
            out["signals"] = item["evidence"]
        return out

    if etype == "dependency":
        out["direction"] = item.get("direction")
        out["id"] = item.get("id")
        out["label"] = item.get("label")
        out["node_type"] = item.get("node_type") or item.get("type")
        if item.get("via"):
            out["via"] = item["via"]
        return out

    if etype == "ownership":
        out["path"] = item.get("path")
        out["owner"] = item.get("owner")
        out["confidence"] = item.get("confidence")
        if item.get("evidence"):
            out["signals"] = item["evidence"]
        return out

    if etype == "hotspot":
        out["path"] = item.get("path")
        out["churn"] = item.get("churn")
        out["commits"] = item.get("commits")
        out["score"] = item.get("score")
        return out

    if etype == "blast_radius":
        out["id"] = item.get("id")
        out["label"] = item.get("label")
        out["node_type"] = item.get("node_type")
        return out

    if etype == "concept_centrality":
        out["concept"] = item.get("concept")
        out["file_count"] = item.get("file_count")
        out["avg_confidence"] = item.get("avg_confidence")
        return out

    # Pass through unknown shapes with a stable envelope
    for key, value in item.items():
        if key != "type":
            out[key] = value
    return out


def format_evidence_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [format_evidence(i) for i in items]

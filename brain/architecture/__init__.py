"""Rule-based architecture inference for layered layouts and patterns."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

LAYER_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("cmd", re.compile(r"(^|/)(cmd|apps?|bin)(/|$)")),
    ("api", re.compile(r"(^|/)(api|handlers?|controllers?|routes?)(/|$)")),
    ("internal", re.compile(r"(^|/)(internal|core|domain)(/|$)")),
    ("pkg", re.compile(r"(^|/)(pkg|lib|shared|common)(/|$)")),
    ("infra", re.compile(r"(^|/)(infra|adapters?|repository|persist|store|db)(/|$)")),
]

PATTERN_HINTS: list[tuple[str, re.Pattern[str]]] = [
    ("repository", re.compile(r"repository|repo\.|/store", re.I)),
    ("handler", re.compile(r"handler|controller|endpoint", re.I)),
    ("factory", re.compile(r"factory|new[A-Z]|create_", re.I)),
    ("middleware", re.compile(r"middleware|interceptor", re.I)),
]


def infer_layer(path: str) -> str:
    p = path.replace("\\", "/")
    for name, pat in LAYER_PATTERNS:
        if pat.search(p):
            return name
    return "other"


def analyze_paths(paths: list[str]) -> dict[str, Any]:
    """Summarize layers and patterns across file paths."""
    layers: dict[str, list[str]] = defaultdict(list)
    patterns: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        layers[infer_layer(path)].append(path)
        for pname, pat in PATTERN_HINTS:
            if pat.search(path):
                patterns[pname].append(path)
    return {
        "layers": {k: sorted(v)[:50] for k, v in sorted(layers.items())},
        "layer_counts": {k: len(v) for k, v in layers.items()},
        "patterns": {k: sorted(v)[:30] for k, v in sorted(patterns.items())},
    }


def safest_place_for_concept(concept: str, tagged_files: list[dict[str, Any]], all_paths: list[str]) -> dict[str, Any]:
    """
    Suggest implementation location: prefer packages already tagged with the concept
    that sit in internal/infra rather than cmd.
    """
    analysis = analyze_paths(all_paths)
    candidates: list[dict[str, Any]] = []
    for f in tagged_files:
        path = str(f.get("label") or f.get("id") or "")
        layer = infer_layer(path)
        score = float(f.get("confidence") or 0.5)
        if layer in ("internal", "infra", "pkg"):
            score += 0.2
        if layer == "cmd":
            score -= 0.25
        candidates.append({"path": path, "layer": layer, "score": round(score, 3)})
    candidates.sort(key=lambda x: x["score"], reverse=True)

    suggestion = candidates[0] if candidates else None
    if suggestion is None and analysis["layers"].get("internal"):
        suggestion = {
            "path": analysis["layers"]["internal"][0],
            "layer": "internal",
            "score": 0.4,
        }

    assumptions = []
    if analysis["layer_counts"].get("cmd") and analysis["layer_counts"].get("internal"):
        assumptions.append("Layered layout detected: cmd → internal/pkg (prefer business logic outside cmd).")
    if analysis["patterns"].get("repository"):
        assumptions.append("Repository/store pattern present — prefer extending existing store modules.")
    return {
        "concept": concept,
        "suggestion": suggestion,
        "candidates": candidates[:8],
        "assumptions": assumptions,
        "layers": analysis["layer_counts"],
    }


def ownership_rollup(
    ownership_rows: list[dict[str, Any]],
    path_prefix: str,
) -> list[dict[str, Any]]:
    """Aggregate ownership for files under a path prefix."""
    tallies: dict[str, float] = defaultdict(float)
    matched = 0
    for row in ownership_rows:
        p = str(row.get("path") or row.get("to") or row.get("id") or "")
        owner = str(row.get("owner") or row.get("author") or row.get("from") or "")
        if not owner:
            continue
        if path_prefix and not (p == path_prefix or p.startswith(path_prefix.rstrip("/") + "/")):
            continue
        matched += 1
        tallies[owner] += float(row.get("confidence") or 1.0)
    ranked = sorted(
        [{"owner": o, "score": round(s, 3), "files": matched} for o, s in tallies.items()],
        key=lambda x: x["score"],
        reverse=True,
    )
    return ranked

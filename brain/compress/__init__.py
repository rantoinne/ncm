"""Repository compression / knowledge capsules (Phase 3 scaffold)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from brain.architecture import analyze_paths, infer_layer


def build_capsules(
    repo_map: dict[str, Any],
    concept_counts: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Compress repo map into layer/subsystem capsules."""
    files = repo_map.get("files") or []
    paths = [str(f.get("path") or f.get("id") or "") for f in files]
    analysis = analyze_paths(paths)
    capsules: list[dict[str, Any]] = []
    for layer, members in analysis["layers"].items():
        capsules.append(
            {
                "id": f"capsule:{layer}",
                "type": "Capsule",
                "label": f"{layer} layer",
                "props": {
                    "layer": layer,
                    "file_count": analysis["layer_counts"].get(layer, 0),
                    "sample_files": members[:12],
                    "responsibility": _layer_blurb(layer),
                },
            }
        )
    if concept_counts:
        top = sorted(concept_counts.items(), key=lambda x: x[1], reverse=True)[:8]
        capsules.append(
            {
                "id": "capsule:concepts",
                "type": "Capsule",
                "label": "Central concepts",
                "props": {"concepts": [{"name": n, "count": c} for n, c in top]},
            }
        )
    return capsules


def _layer_blurb(layer: str) -> str:
    return {
        "cmd": "Entrypoints and CLIs",
        "api": "HTTP/RPC handlers",
        "internal": "Core domain / business logic",
        "pkg": "Reusable libraries",
        "infra": "Persistence and adapters",
        "other": "Unclassified paths",
    }.get(layer, "Subsystem")

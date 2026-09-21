"""ADR / design-doc ingest into the knowledge graph."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

ADR_NAME_RE = re.compile(r"(?i)(adr[-_]?|decision[-_]?|rfc[-_]?)[\w.-]+\.md$")
DOC_GLOBS = ("**/docs/**/*.md", "**/adr/**/*.md", "**/architecture/**/*.md", "**/rfcs/**/*.md")


def discover_docs(repo_root: str | Path, limit: int = 200) -> list[Path]:
    root = Path(repo_root)
    found: list[Path] = []
    if not root.exists():
        return found
    for pattern in DOC_GLOBS:
        for p in root.glob(pattern):
            if p.is_file() and p.suffix.lower() == ".md":
                found.append(p)
            if len(found) >= limit:
                return found
    # Also pick ADR-named files anywhere
    for p in root.rglob("*.md"):
        if ADR_NAME_RE.search(p.name):
            found.append(p)
        if len(found) >= limit:
            break
    # Dedupe
    seen: set[str] = set()
    out: list[Path] = []
    for p in found:
        key = str(p.resolve())
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:limit]


def docs_to_graph(
    docs: list[Path],
    repo_root: str | Path,
    repo_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (nodes, edges) for ADR/RFC/doc files."""
    root = Path(repo_root)
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for path in docs:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        text = ""
        try:
            text = path.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        title = path.stem
        for line in text.splitlines()[:20]:
            if line.startswith("#"):
                title = line.lstrip("#").strip() or title
                break
        doc_id = f"doc:{rel}"
        kind = "ADR" if ADR_NAME_RE.search(path.name) or "/adr/" in rel.lower() else "Doc"
        if "rfc" in path.name.lower():
            kind = "RFC"
        nodes.append(
            {
                "id": doc_id,
                "type": kind,
                "label": title,
                "props": {
                    "repo_id": repo_id,
                    "path": rel,
                    "title": title,
                    "excerpt": text[:280],
                },
            }
        )
        # Link to files mentioned in backticks
        for m in re.finditer(r"`([A-Za-z0-9_./\-]+\.[A-Za-z0-9]+)`", text):
            target = m.group(1)
            edges.append(
                {
                    "id": f"{doc_id}-REFERS_TO-{target}",
                    "type": "REFERS_TO",
                    "from": doc_id,
                    "to": target,
                    "confidence": 0.6,
                    "evidence": ["doc mention"],
                }
            )
    return nodes, edges

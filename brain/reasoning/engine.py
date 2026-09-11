"""Intent parser and template-based reasoner over the NCM graph."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from brain.concepts.tagger import CONCEPTS
from brain.explain.formatter import format_evidence_list, format_path


class Intent(str, Enum):
    WHERE_LIVES = "where_lives"
    DEPENDS_ON = "depends_on"
    OWNERSHIP = "ownership"
    HOTSPOTS = "hotspots"
    INTRODUCED = "introduced"
    BLAST_RADIUS = "blast_radius"
    CONCEPT_CENTRALITY = "concept_centrality"
    UNKNOWN = "unknown"


class _Store(Protocol):
    def neighbors(self, node_id: str, depth: int = 1) -> list[dict[str, Any]]: ...
    def shortest_path(self, from_id: str, to_id: str) -> list[dict[str, Any]]: ...
    def upstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]: ...
    def downstream_deps(self, node_id: str, max_depth: int = 5) -> list[dict[str, Any]]: ...
    def blast_radius(self, node_id: str, max_depth: int = 3) -> dict[str, Any]: ...
    def get_repo_map(self, repo_id: str) -> dict[str, Any]: ...
    def files_by_concept(self, concept: str, repo_id: str = "") -> list[dict[str, Any]]: ...
    def ownership_for_path(self, path: str, repo_id: str = "") -> list[dict[str, Any]]: ...
    def hotspots(self, repo_id: str = "", limit: int = 10) -> list[dict[str, Any]]: ...


@dataclass
class ParsedIntent:
    intent: Intent
    concept: str | None = None
    target: str | None = None
    raw: str = ""
    confidence: float = 0.5


@dataclass
class QueryResponse:
    answer: str
    confidence: float
    evidence: list[dict[str, Any]] = field(default_factory=list)
    alternatives: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "alternatives": self.alternatives,
        }


class IntentParser:
    """Classify natural-language questions into structured intents."""

    _CONCEPT_ALIASES: dict[str, str] = {
        "authentication": "auth",
        "authorization": "auth",
        "login": "auth",
        "persist": "persistence",
        "database": "persistence",
        "db": "persistence",
        "logs": "logging",
        "logger": "logging",
        "tests": "testing",
        "test": "testing",
        "network": "networking",
        "http": "networking",
        "ttl": "expiration",
        "expire": "expiration",
        "expiry": "expiration",
        "proto": "protocol",
        "parser": "protocol",
        "store": "storage",
        "storage": "storage",
        "cache": "cache",
        "retry": "retry",
        "config": "config",
        "configuration": "config",
        "middleware": "middleware",
        "auth": "auth",
        "persistence": "persistence",
        "logging": "logging",
        "testing": "testing",
        "networking": "networking",
        "expiration": "expiration",
        "protocol": "protocol",
    }

    def parse(self, question: str) -> ParsedIntent:
        q = (question or "").strip()
        lower = q.lower()

        concept = self._extract_concept(lower)
        target = self._extract_target(q)

        if re.search(r"\b(hotspot|change most|churn|most (often|frequently) change|likely to break)\b", lower):
            return ParsedIntent(Intent.HOTSPOTS, concept=concept, target=target, raw=q, confidence=0.9)

        if re.search(r"\b(who owns|ownership|who understands|maintainer|blame)\b", lower):
            return ParsedIntent(Intent.OWNERSHIP, concept=concept, target=target, raw=q, confidence=0.88)

        if re.search(r"\b(blast radius|if (we |I )?(delete|remove|break)|what fails|impact of)\b", lower):
            return ParsedIntent(Intent.BLAST_RADIUS, concept=concept, target=target, raw=q, confidence=0.9)

        if re.search(r"\b(when (was|were).*(introduc|add|creat)|introduced|first appear|why was this abstraction)\b", lower):
            return ParsedIntent(Intent.INTRODUCED, concept=concept, target=target, raw=q, confidence=0.75)

        if re.search(r"\b(depend(s|ed)? on|what uses|coupled|indirectly coupled|imports)\b", lower):
            return ParsedIntent(Intent.DEPENDS_ON, concept=concept, target=target, raw=q, confidence=0.9)

        if re.search(r"\b(central concept|concept centrality|key concepts|main concepts)\b", lower):
            return ParsedIntent(Intent.CONCEPT_CENTRALITY, concept=concept, target=target, raw=q, confidence=0.85)

        if re.search(r"\b(where (does|is|do)|where.*live|lives in|located)\b", lower) or concept:
            conf = 0.92 if concept else 0.55
            return ParsedIntent(Intent.WHERE_LIVES, concept=concept, target=target, raw=q, confidence=conf)

        if target and re.search(r"\b(depend|import|call|use)\b", lower):
            return ParsedIntent(Intent.DEPENDS_ON, concept=concept, target=target, raw=q, confidence=0.7)

        return ParsedIntent(Intent.UNKNOWN, concept=concept, target=target, raw=q, confidence=0.3)

    def _extract_concept(self, lower: str) -> str | None:
        # Prefer longer alias matches
        for alias in sorted(self._CONCEPT_ALIASES.keys(), key=len, reverse=True):
            if re.search(rf"\b{re.escape(alias)}\b", lower):
                return self._CONCEPT_ALIASES[alias]
        for c in CONCEPTS:
            if re.search(rf"\b{re.escape(c)}\b", lower):
                return c
        return None

    def _extract_target(self, question: str) -> str | None:
        # Backtick or quoted path/module
        for pat in (
            r"`([^`]+)`",
            r'"([^"]+)"',
            r"'([^']+)'",
            r"\b((?:internal|pkg|cmd|src|lib|app)/[A-Za-z0-9_./\-]+)",
            r"\b([A-Za-z_][A-Za-z0-9_]*(?:/[A-Za-z0-9_./\-]+)+)\b",
        ):
            m = re.search(pat, question)
            if m:
                return m.group(1).strip()
        return None


class Reasoner:
    """Build evidence bundles and template answers from graph store queries."""

    def __init__(self, store: _Store, repo_id: str = "") -> None:
        self.store = store
        self.repo_id = repo_id
        self.parser = IntentParser()

    def answer(self, question: str, repo_id: str | None = None) -> QueryResponse:
        from brain.logging_config import get_logger

        log = get_logger("ncm.reasoning")
        rid = repo_id or self.repo_id
        parsed = self.parser.parse(question)
        log.debug(
            "intent=%s concept=%s target=%s confidence=%.2f",
            parsed.intent,
            parsed.concept,
            parsed.target,
            parsed.confidence,
        )
        response = self._dispatch(parsed, rid)
        enhanced = self._maybe_llm_enhance(question, response)
        return enhanced

    def _dispatch(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        if parsed.intent == Intent.WHERE_LIVES:
            return self._where_lives(parsed, repo_id)
        if parsed.intent == Intent.DEPENDS_ON:
            return self._depends_on(parsed, repo_id)
        if parsed.intent == Intent.OWNERSHIP:
            return self._ownership(parsed, repo_id)
        if parsed.intent == Intent.HOTSPOTS:
            return self._hotspots(parsed, repo_id)
        if parsed.intent == Intent.BLAST_RADIUS:
            return self._blast_radius(parsed, repo_id)
        if parsed.intent == Intent.INTRODUCED:
            return self._introduced(parsed, repo_id)
        if parsed.intent == Intent.CONCEPT_CENTRALITY:
            return self._concept_centrality(parsed, repo_id)
        return QueryResponse(
            answer=(
                "I could not classify that question confidently. "
                "Try asking where a concept lives, what depends on a module, "
                "who owns a path, or which files are hotspots."
            ),
            confidence=parsed.confidence,
            evidence=[],
            alternatives=[
                "Where does authentication live?",
                "What depends on internal/store?",
                "Which files change most often?",
            ],
        )

    def _resolve_node_id(self, target: str | None, repo_id: str) -> str | None:
        if not target:
            return None
        target = target.strip().strip("`\"'")
        candidates = [
            target,
            f"pkg:{target}",
            f"pkg:{target.split('/')[-1]}",
            f"file:{target}",
            f"module:{target}",
            f"package:{target}",
            f"import:{target}",
        ]
        # Prefer exact package / module hits first (module-path style queries).
        if hasattr(self.store, "nodes"):
            for c in candidates:
                node = self.store.nodes.get(c)
                if node and node.get("type") in ("Package", "Module", "Concept"):
                    return c
            if f"pkg:{target}" in self.store.nodes:
                return f"pkg:{target}"

        repo_map = self.store.get_repo_map(repo_id) if repo_id else {"files": [], "modules": []}
        for m in repo_map.get("modules") or []:
            label = str(m.get("label") or "")
            mid = m.get("id")
            if target == label or target == mid or label.endswith(target) or mid == f"pkg:{target}":
                return mid
        for f in repo_map.get("files") or []:
            p = str(f.get("path") or f.get("label") or f.get("id") or "")
            fid = f.get("id")
            if target == p or target == fid:
                return fid
        # Path prefix → package containing those files
        if hasattr(self.store, "nodes"):
            pkg_candidate = f"pkg:{target}"
            if pkg_candidate in self.store.nodes:
                return pkg_candidate
            for nid, node in self.store.nodes.items():
                if node.get("type") == "Package" and (
                    nid == f"pkg:{target}"
                    or str(node.get("label") or "") == target
                    or str(node.get("label") or "").endswith(target)
                ):
                    return nid
            for nid, node in self.store.nodes.items():
                label = str(node.get("label") or "")
                path = str((node.get("props") or {}).get("path") or "")
                if target == nid or target == path:
                    return nid
                if node.get("type") == "File" and (path.startswith(target + "/") or path == target):
                    # Fall back to file only if no package matched
                    continue
            # Last resort: a file under that directory
            for nid, node in self.store.nodes.items():
                path = str((node.get("props") or {}).get("path") or nid)
                if node.get("type") == "File" and (path == target or path.startswith(target + "/")):
                    return nid
        for c in candidates:
            if hasattr(self.store, "nodes") and c in self.store.nodes:
                return c
        return target

    def _where_lives(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        concept = parsed.concept or "persistence"
        files = self.store.files_by_concept(concept, repo_id=repo_id)
        evidence: list[dict[str, Any]] = [
            {
                "type": "concept_match",
                "concept": concept,
                "node_id": f.get("id"),
                "label": f.get("label"),
                "confidence": f.get("confidence"),
                "evidence": f.get("evidence"),
            }
            for f in files[:15]
        ]
        if not files:
            return QueryResponse(
                answer=f"No code is currently tagged as **{concept}**. Index the repo and ensure concept tagging has run.",
                confidence=0.2,
                evidence=[],
                alternatives=[f"Where does {c} live?" for c in CONCEPTS[:3]],
            )
        top = files[:5]
        locs = ", ".join(str(f.get("label") or f.get("id")) for f in top)
        avg_conf = sum(float(f.get("confidence") or 0) for f in top) / max(len(top), 1)
        answer = f"{concept.capitalize()} primarily lives in: {locs}."
        if len(files) > 5:
            answer += f" ({len(files)} locations tagged in total.)"
        return QueryResponse(
            answer=answer,
            confidence=min(0.95, avg_conf),
            evidence=format_evidence_list(evidence),
            alternatives=[f"What depends on {top[0].get('label')}?"] if top else [],
        )

    def _depends_on(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        target = parsed.target
        node_id = self._resolve_node_id(target, repo_id)
        if not node_id:
            return QueryResponse(
                answer="Specify a module or file path to inspect dependencies (e.g. `internal/store`).",
                confidence=0.25,
                evidence=[],
                alternatives=[],
            )
        downstream = self.store.downstream_deps(node_id, max_depth=4)
        upstream = self.store.upstream_deps(node_id, max_depth=3)
        evidence: list[dict[str, Any]] = []
        for n in downstream[:20]:
            evidence.append(
                {
                    "type": "dependency",
                    "direction": "downstream",
                    "id": n.get("id"),
                    "label": n.get("label"),
                    "node_type": n.get("type"),
                    "via": n.get("via"),
                }
            )
        for n in upstream[:10]:
            evidence.append(
                {
                    "type": "dependency",
                    "direction": "upstream",
                    "id": n.get("id"),
                    "label": n.get("label"),
                    "node_type": n.get("type"),
                    "via": n.get("via"),
                }
            )
        if not downstream and not upstream:
            # Node may exist with only CONTAINS / no importers yet.
            neighbors = self.store.neighbors(node_id, depth=1)
            contained = [n for n in neighbors if n.get("type") == "File"]
            if contained or (hasattr(self.store, "nodes") and node_id in self.store.nodes):
                files = ", ".join(str(n.get("label") or n.get("id")) for n in contained[:8]) or "(no files)"
                return QueryResponse(
                    answer=(
                        f"`{target or node_id}` is indexed ({len(contained)} file(s): {files}), "
                        f"but nothing currently depends on it via IMPORTS/DEPENDS_ON."
                    ),
                    confidence=0.55,
                    evidence=format_evidence_list(
                        [
                            {
                                "type": "graph_node",
                                "id": node_id,
                                "label": target,
                                "files": [n.get("id") for n in contained[:10]],
                            }
                        ]
                    ),
                    alternatives=[f"Where does persistence live?", f"What is the blast radius of {target}?"],
                )
            return QueryResponse(
                answer=f"No dependency edges found for `{target or node_id}` yet.",
                confidence=0.35,
                evidence=[],
                alternatives=[],
            )
        dep_labels = [str(n.get("label") or n.get("id")) for n in downstream[:8]]
        answer = (
            f"Things that depend on `{target or node_id}`: "
            + (", ".join(dep_labels) if dep_labels else "(none found)")
            + "."
        )
        if upstream:
            up_labels = [str(n.get("label") or n.get("id")) for n in upstream[:5]]
            answer += f" It depends on: {', '.join(up_labels)}."
        conf = 0.8 if downstream else 0.55
        return QueryResponse(
            answer=answer,
            confidence=conf,
            evidence=format_evidence_list(evidence),
            alternatives=[f"What is the blast radius of {target}?"],
        )

    def _ownership(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        target = parsed.target or ""
        if not target and parsed.concept:
            files = self.store.files_by_concept(parsed.concept, repo_id=repo_id)
            target = str((files[0].get("label") if files else "") or "")
        if not target:
            return QueryResponse(
                answer="Specify a path to look up ownership (e.g. who owns `internal/store`?).",
                confidence=0.25,
                evidence=[],
                alternatives=[],
            )
        owners = self.store.ownership_for_path(target, repo_id=repo_id)
        evidence = [
            {
                "type": "ownership",
                "path": o.get("path"),
                "owner": o.get("owner"),
                "confidence": o.get("confidence"),
                "evidence": o.get("evidence"),
            }
            for o in owners[:10]
        ]
        if not owners:
            return QueryResponse(
                answer=f"No ownership data found for `{target}`. Ensure git artifacts were indexed.",
                confidence=0.3,
                evidence=[],
                alternatives=[],
            )
        top = owners[0]
        answer = (
            f"`{top.get('path') or target}` is primarily owned by "
            f"**{top.get('owner')}** (confidence {float(top.get('confidence') or 0):.2f})."
        )
        if len(owners) > 1:
            alts = ", ".join(f"{o.get('owner')} ({float(o.get('confidence') or 0):.2f})" for o in owners[1:4])
            answer += f" Other contributors: {alts}."
        return QueryResponse(
            answer=answer,
            confidence=float(top.get("confidence") or 0.5),
            evidence=format_evidence_list(evidence),
            alternatives=[],
        )

    def _hotspots(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        spots = self.store.hotspots(repo_id=repo_id, limit=10)
        evidence = [
            {
                "type": "hotspot",
                "path": s.get("path"),
                "churn": s.get("churn"),
                "commits": s.get("commits"),
                "score": s.get("score"),
            }
            for s in spots
        ]
        if not spots:
            return QueryResponse(
                answer="No hotspot data available. Index git history to compute churn.",
                confidence=0.25,
                evidence=[],
                alternatives=[],
            )
        lines = [f"{s.get('path')} (score={s.get('score')})" for s in spots[:5]]
        answer = "Highest-churn files: " + "; ".join(lines) + "."
        return QueryResponse(
            answer=answer,
            confidence=0.85,
            evidence=format_evidence_list(evidence),
            alternatives=["What is the blast radius of the top hotspot?"],
        )

    def _blast_radius(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        target = parsed.target
        node_id = self._resolve_node_id(target, repo_id)
        if not node_id:
            return QueryResponse(
                answer="Specify a module/file for blast-radius analysis.",
                confidence=0.25,
                evidence=[],
                alternatives=[],
            )
        br = self.store.blast_radius(node_id, max_depth=3)
        affected = br.get("affected") or []
        evidence = [
            {
                "type": "blast_radius",
                "id": n.get("id"),
                "label": n.get("label"),
                "node_type": n.get("type"),
            }
            for n in affected[:25]
        ]
        by_type = br.get("by_type") or {}
        type_summary = ", ".join(f"{k}={v}" for k, v in by_type.items()) or "none"
        answer = (
            f"Blast radius of `{target or node_id}`: {br.get('affected_count', 0)} downstream nodes "
            f"within depth {br.get('max_depth')} ({type_summary})."
        )
        if affected:
            sample = ", ".join(str(n.get("label") or n.get("id")) for n in affected[:5])
            answer += f" Examples: {sample}."
        conf = 0.8 if affected else 0.4
        return QueryResponse(
            answer=answer,
            confidence=conf,
            evidence=format_evidence_list(evidence),
            alternatives=[],
        )

    def _introduced(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        target = parsed.target or parsed.concept or ""
        # Look for INTRODUCED_IN edges via neighbors if store exposes them through ownership/path
        node_id = self._resolve_node_id(parsed.target, repo_id) if parsed.target else None
        evidence: list[dict[str, Any]] = []
        commits: list[str] = []
        if node_id:
            for n in self.store.neighbors(node_id, depth=2):
                if n.get("type") == "Commit":
                    commits.append(str(n.get("label") or n.get("id")))
                    evidence.append({"type": "commit", "id": n.get("id"), "label": n.get("label"), "props": n.get("props")})
        if not evidence:
            return QueryResponse(
                answer=(
                    f"No introduction commit linked for `{target or 'that target'}` yet. "
                    "Ensure git INTRODUCED_IN edges are present in the graph."
                ),
                confidence=0.3,
                evidence=[],
                alternatives=["Who owns this path?", "Which files change most often?"],
            )
        answer = f"`{target}` appears linked to commit(s): {', '.join(commits[:5])}."
        return QueryResponse(
            answer=answer,
            confidence=0.65,
            evidence=format_evidence_list(evidence),
            alternatives=[],
        )

    def _concept_centrality(self, parsed: ParsedIntent, repo_id: str) -> QueryResponse:
        scores: list[tuple[str, int, float]] = []
        for concept in CONCEPTS:
            files = self.store.files_by_concept(concept, repo_id=repo_id)
            if not files:
                continue
            avg = sum(float(f.get("confidence") or 0) for f in files) / len(files)
            scores.append((concept, len(files), avg))
        scores.sort(key=lambda x: (-x[1], -x[2]))
        evidence = [
            {"type": "concept_centrality", "concept": c, "file_count": n, "avg_confidence": round(a, 3)}
            for c, n, a in scores[:12]
        ]
        if not scores:
            return QueryResponse(
                answer="No concepts tagged yet. Run indexing with concept tagging first.",
                confidence=0.2,
                evidence=[],
                alternatives=[],
            )
        top = ", ".join(f"{c} ({n} files)" for c, n, _ in scores[:5])
        return QueryResponse(
            answer=f"Most central concepts by tagged file coverage: {top}.",
            confidence=0.8,
            evidence=format_evidence_list(evidence),
            alternatives=[f"Where does {scores[0][0]} live?"],
        )

    def _maybe_llm_enhance(self, question: str, response: QueryResponse) -> QueryResponse:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            return response
        try:
            import httpx

            evidence_summary = format_evidence_list(response.evidence)[:8]
            prompt = (
                "You are NCM, a codebase memory assistant. Rewrite the answer clearly "
                "using ONLY the provided evidence. Do not invent files or commits.\n\n"
                f"Question: {question}\n"
                f"Draft answer: {response.answer}\n"
                f"Evidence: {evidence_summary}\n"
            )
            payload = {
                "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": "Answer concisely from evidence only."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            }
            with httpx.Client(timeout=20.0) as client:
                r = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {api_key}"},
                    json=payload,
                )
                if r.status_code >= 400:
                    return response
                data = r.json()
                text = data["choices"][0]["message"]["content"].strip()
                if text:
                    response.answer = text
                    response.confidence = min(0.98, response.confidence + 0.05)
        except Exception:
            return response
        return response


def path_between(store: _Store, from_id: str, to_id: str) -> dict[str, Any]:
    nodes = store.shortest_path(from_id, to_id)
    return {
        "from": from_id,
        "to": to_id,
        "path": nodes,
        "formatted": format_path(nodes),
        "length": max(0, len(nodes) - 1) if nodes else 0,
    }

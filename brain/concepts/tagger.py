"""Rule-based concept tagger using path, name, and import heuristics."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from brain.loader.artifacts import FileArtifact

CONCEPTS: tuple[str, ...] = (
    "auth",
    "cache",
    "retry",
    "config",
    "persistence",
    "networking",
    "logging",
    "testing",
    "middleware",
    "expiration",
    "protocol",
    "storage",
)

# Path / filename / symbol-name heuristics (regex fragments, case-insensitive).
PATH_NAME_RULES: dict[str, list[str]] = {
    "auth": [r"auth", r"login", r"oauth", r"jwt", r"session", r"permission", r"rbac", r"acl"],
    "cache": [r"cache", r"lru", r"memoiz", r"redis"],
    "retry": [r"retry", r"backoff", r"circuit.?break"],
    "config": [r"config", r"settings?", r"env(ironment)?", r"flag"],
    "persistence": [r"persist", r"repository", r"repo/", r"/store", r"datastore", r"snapshot"],
    "networking": [r"network", r"http", r"tcp", r"udp", r"socket", r"client", r"server", r"transport"],
    "logging": [r"log(ger|ging)?", r"slog", r"zap", r"telemetry", r"trace", r"metric"],
    "testing": [r"_test\.", r"/test/", r"/tests/", r"mock", r"fixture", r"spec\."],
    "middleware": [r"middleware", r"interceptor", r"filter", r"hook"],
    "expiration": [r"expir", r"ttl", r"timeout", r"deadline", r"lease", r"evict"],
    "protocol": [r"protocol", r"protobuf", r"proto", r"codec", r"serializer", r"parser", r"resp", r"wire"],
    "storage": [r"storage", r"blob", r"s3", r"filesystem", r"disk", r"volume", r"bucket"],
}

# Import / dependency package signals.
IMPORT_RULES: dict[str, list[str]] = {
    "auth": ["jwt", "oauth", "passport", "bcrypt", "crypto/x509", "golang.org/x/crypto"],
    "cache": ["redis", "memcache", " ristretto", "groupcache", "lru"],
    "retry": ["retry", "backoff", "resilience4j", "tenacity", "cenkalti/backoff"],
    "config": ["viper", "envconfig", "dotenv", "pydantic_settings", "cobra", "flag"],
    "persistence": ["sql", "gorm", "sqlx", "sqlalchemy", "prisma", "mongo", "sqlite", "postgres", "database/sql"],
    "networking": ["net/http", "httpx", "requests", "axios", "grpc", "websocket", "fasthttp", "gin-gonic", "echo"],
    "logging": ["slog", "zap", "logrus", "zerolog", "logging", "logrus", "pino", "winston"],
    "testing": ["testing", "pytest", "jest", "mocha", "testify", "gomock", "unittest"],
    "middleware": ["middleware", "chi/", "gorilla/mux", "express"],
    "expiration": ["ttl", "cache/"],
    "protocol": ["grpc", "protobuf", "proto", "thrift", "avro", "msgpack", "encoding/json", "encoding/gob"],
    "storage": ["aws-sdk", "minio", "s3", "blob", "os", "io/fs", "afero"],
}


@dataclass
class ConceptTag:
    node_id: str
    concept: str
    confidence: float
    evidence: list[str] = field(default_factory=list)

    def to_edge(self) -> dict[str, Any]:
        """Return a TAGGED_AS edge spec for graph ingest."""
        return {
            "id": f"{self.node_id}->concept:{self.concept}:TAGGED_AS",
            "type": "TAGGED_AS",
            "from": self.node_id,
            "to": f"concept:{self.concept}",
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "concept": self.concept,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
        }


def _score_text(text: str, patterns: list[str]) -> tuple[float, list[str]]:
    hits: list[str] = []
    lower = text.lower()
    for pat in patterns:
        if re.search(pat, lower, re.IGNORECASE):
            hits.append(pat)
    if not hits:
        return 0.0, []
    # Diminishing returns for multiple hits
    confidence = min(0.95, 0.45 + 0.15 * len(hits))
    return confidence, hits


def _score_imports(imports: list[str], needles: list[str]) -> tuple[float, list[str]]:
    hits: list[str] = []
    joined = " ".join(imports).lower()
    for needle in needles:
        n = needle.lower().strip()
        if not n:
            continue
        if n in joined or any(n in imp.lower() for imp in imports):
            hits.append(needle)
    if not hits:
        return 0.0, []
    confidence = min(0.98, 0.55 + 0.12 * len(hits))
    return confidence, [f"import:{h}" for h in hits]


def _file_node_id(artifact: FileArtifact) -> str:
    # Match Go graph file node IDs (relative path, no prefix).
    return artifact.file_id or artifact.path


def _symbol_node_id(artifact: FileArtifact, symbol_id: str, symbol_name: str) -> str:
    if symbol_id:
        return symbol_id
    return f"{_file_node_id(artifact)}#{symbol_name}"


def tag_artifacts(files: list[FileArtifact]) -> list[dict[str, Any]]:
    """
    Tag file and symbol nodes with concepts.

    Returns a list of dicts: {node_id, concept, confidence, evidence}
    suitable for creating TAGGED_AS edges via ConceptTag.to_edge().
    """
    tags: dict[tuple[str, str], ConceptTag] = {}

    def add_tag(node_id: str, concept: str, confidence: float, evidence: list[str]) -> None:
        if confidence < 0.4:
            return
        key = (node_id, concept)
        existing = tags.get(key)
        if existing is None or confidence > existing.confidence:
            tags[key] = ConceptTag(
                node_id=node_id,
                concept=concept,
                confidence=round(confidence, 3),
                evidence=evidence[:8],
            )
        elif existing is not None:
            # Merge evidence
            merged = list(dict.fromkeys(existing.evidence + evidence))[:8]
            existing.evidence = merged
            existing.confidence = round(max(existing.confidence, confidence), 3)

    for art in files:
        path = art.file_id or art.path or ""
        package = art.package or ""
        blob = f"{path} {package}"
        file_id = _file_node_id(art)

        for concept in CONCEPTS:
            conf_p, ev_p = _score_text(blob, PATH_NAME_RULES.get(concept, []))
            conf_i, ev_i = _score_imports(art.imports, IMPORT_RULES.get(concept, []))
            combined = max(conf_p, conf_i)
            if conf_p and conf_i:
                combined = min(0.99, (conf_p + conf_i) / 2 + 0.15)
            evidence = [f"path:{e}" for e in ev_p] + ev_i
            add_tag(file_id, concept, combined, evidence)

            # Comment hints
            comment_text = " ".join(art.comments[:20]).lower()
            if comment_text:
                conf_c, ev_c = _score_text(comment_text, PATH_NAME_RULES.get(concept, []))
                if conf_c:
                    add_tag(
                        file_id,
                        concept,
                        min(0.85, conf_c * 0.9),
                        [f"comment:{e}" for e in ev_c],
                    )

        for sym in art.symbols:
            sym_blob = f"{sym.name} {sym.signature} {sym.kind}"
            sym_id = _symbol_node_id(art, sym.id, sym.name)
            for concept in CONCEPTS:
                conf_s, ev_s = _score_text(sym_blob, PATH_NAME_RULES.get(concept, []))
                if conf_s:
                    add_tag(sym_id, concept, conf_s, [f"symbol:{e}" for e in ev_s])

    return [t.to_dict() for t in tags.values()]


def tags_to_edges(tags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert tag dicts to TAGGED_AS edge specs and Concept nodes."""
    edges: list[dict[str, Any]] = []
    for t in tags:
        tag = ConceptTag(
            node_id=t["node_id"],
            concept=t["concept"],
            confidence=float(t.get("confidence", 0.5)),
            evidence=list(t.get("evidence") or []),
        )
        edges.append(tag.to_edge())
    return edges


def concept_nodes(tags: list[dict[str, Any]], repo_id: str = "") -> list[dict[str, Any]]:
    """Emit Concept nodes referenced by tags."""
    seen: set[str] = set()
    nodes: list[dict[str, Any]] = []
    for t in tags:
        concept = t["concept"]
        cid = f"concept:{concept}"
        if cid in seen:
            continue
        seen.add(cid)
        props: dict[str, Any] = {"name": concept}
        if repo_id:
            props["repo_id"] = repo_id
        nodes.append({"id": cid, "type": "Concept", "label": concept, "props": props})
    return nodes

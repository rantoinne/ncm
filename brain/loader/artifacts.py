"""Pydantic models and loaders for Go-produced NCM JSON artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Symbol(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = ""
    name: str
    kind: str = ""
    signature: str = ""
    start_line: int = 0
    end_line: int = 0
    calls: list[str] = Field(default_factory=list)


class FileArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str = ""
    rel_path: str = ""
    language: str = ""
    package: str = ""
    imports: list[str] = Field(default_factory=list)
    symbols: list[Symbol] = Field(default_factory=list)
    comments: list[str] = Field(default_factory=list)
    hash: str = ""

    @model_validator(mode="after")
    def _normalize_path(self) -> FileArtifact:
        # Prefer relative path as the canonical file identity (matches Go graph IDs).
        if self.rel_path:
            self.path = self.rel_path.replace("\\", "/")
        elif self.path:
            # Absolute path fallback: keep basename-relative if possible
            self.path = self.path.replace("\\", "/")
        return self

    @property
    def file_id(self) -> str:
        return self.rel_path or self.path


class Manifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo_id: str = ""
    root: str = ""
    repo_root: str = ""
    commit_sha: str = ""
    languages: dict[str, int] = Field(default_factory=dict)
    file_count: int = 0
    scanned_at: str = ""
    indexed_at: str = ""
    module_roots: list[str] = Field(default_factory=list)
    version: str = ""

    @model_validator(mode="after")
    def _normalize(self) -> Manifest:
        if not self.root and self.repo_root:
            self.root = self.repo_root
        if not self.repo_root and self.root:
            self.repo_root = self.root
        if not self.scanned_at and self.indexed_at:
            self.scanned_at = self.indexed_at
        if not self.repo_id:
            root = self.root or self.repo_root or "repo"
            self.repo_id = Path(root).name or "repo"
        # languages may arrive as {lang: count} already from Go
        if self.languages and any(isinstance(v, list) for v in self.languages.values()):
            self.languages = {k: len(v) if isinstance(v, list) else int(v) for k, v in self.languages.items()}
        return self


class GraphNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    type: str
    label: str = ""
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str = ""
    type: str
    from_id: str = Field(default="", alias="from")
    to: str = ""
    confidence: float = 1.0
    evidence: list[str] = Field(default_factory=list)


class GraphArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    cycles: list[list[str]] = Field(default_factory=list)


class AuthorStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str = ""
    email: str = ""
    commits: int = 0


class GitFileStats(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    commits: int = 0
    commit_count: int = 0
    authors: list[AuthorStats] = Field(default_factory=list)
    churn: float = 0.0
    owner: str = ""

    @model_validator(mode="after")
    def _normalize(self) -> GitFileStats:
        if not self.commits and self.commit_count:
            self.commits = self.commit_count
        elif not self.commit_count and self.commits:
            self.commit_count = self.commits
        return self


class GitCommit(BaseModel):
    model_config = ConfigDict(extra="ignore")

    sha: str
    message: str = ""
    author: str = ""
    email: str = ""
    date: str = ""

    @field_validator("date", mode="before")
    @classmethod
    def _date_to_str(cls, v: Any) -> str:
        if v is None:
            return ""
        return str(v)


class Ownership(BaseModel):
    model_config = ConfigDict(extra="ignore")

    path: str
    owner: str = ""
    confidence: float = 0.0


class Rename(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    from_path: str = Field(default="", alias="from")
    to: str = ""
    sha: str = ""


class EdgeHint(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    type: str
    from_id: str = Field(default="", alias="from")
    to: str = ""
    confidence: float = 0.8
    evidence: list[str] = Field(default_factory=list)


class GitArtifact(BaseModel):
    model_config = ConfigDict(extra="ignore")

    repo_root: str = ""
    head: str = ""
    files: list[GitFileStats] = Field(default_factory=list)
    commits: list[GitCommit] = Field(default_factory=list)
    ownership: list[Ownership] = Field(default_factory=list)
    renames: list[Rename] = Field(default_factory=list)
    hotspots: list[dict[str, Any]] = Field(default_factory=list)
    edge_hints: list[EdgeHint] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_go_shape(cls, data: Any) -> Any:
        """Accept Go git.json where files is a map and ownership is embedded."""
        if not isinstance(data, dict):
            return data
        raw = dict(data)

        files_raw = raw.get("files")
        file_list: list[dict[str, Any]] = []
        ownership: list[dict[str, Any]] = list(raw.get("ownership") or [])

        if isinstance(files_raw, dict):
            for path, stats in files_raw.items():
                if not isinstance(stats, dict):
                    continue
                entry = dict(stats)
                entry.setdefault("path", path)
                # authors may be map[name]count
                authors = entry.get("authors")
                if isinstance(authors, dict):
                    entry["authors"] = [
                        {"name": name, "commits": int(count)}
                        for name, count in authors.items()
                    ]
                commits = int(entry.get("commit_count") or entry.get("commits") or 0)
                entry["commits"] = commits
                entry["commit_count"] = commits
                file_list.append(entry)
                owner = entry.get("owner") or ""
                if owner:
                    ownership.append(
                        {
                            "path": entry["path"],
                            "owner": owner,
                            "confidence": 0.7 if commits else 0.4,
                        }
                    )
            raw["files"] = file_list
        elif isinstance(files_raw, list):
            normalized = []
            for entry in files_raw:
                if not isinstance(entry, dict):
                    continue
                e = dict(entry)
                authors = e.get("authors")
                if isinstance(authors, dict):
                    e["authors"] = [
                        {"name": name, "commits": int(count)}
                        for name, count in authors.items()
                    ]
                normalized.append(e)
                if e.get("owner") and not ownership:
                    ownership.append(
                        {
                            "path": e.get("path", ""),
                            "owner": e["owner"],
                            "confidence": 0.7,
                        }
                    )
            raw["files"] = normalized

        if ownership and not raw.get("ownership"):
            # de-dupe by path
            by_path: dict[str, dict[str, Any]] = {}
            for o in ownership:
                by_path[o["path"]] = o
            raw["ownership"] = list(by_path.values())

        if raw.get("renames") is None:
            raw["renames"] = []

        return raw


class ArtifactBundle(BaseModel):
    """All artifacts loaded from a data directory."""

    data_dir: str
    manifest: Manifest
    files: list[FileArtifact]
    graph: GraphArtifact
    git: GitArtifact


def _read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_manifest(data_dir: str | Path) -> Manifest:
    path = Path(data_dir) / "manifest.json"
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    return Manifest.model_validate(_read_json(path))


def load_file_artifacts(data_dir: str | Path) -> list[FileArtifact]:
    files_dir = Path(data_dir) / "files"
    if not files_dir.is_dir():
        return []
    artifacts: list[FileArtifact] = []
    for path in sorted(files_dir.glob("*.json")):
        artifacts.append(FileArtifact.model_validate(_read_json(path)))
    return artifacts


def load_graph(data_dir: str | Path) -> GraphArtifact:
    path = Path(data_dir) / "graph.json"
    if not path.exists():
        return GraphArtifact()
    return GraphArtifact.model_validate(_read_json(path))


def load_git(data_dir: str | Path) -> GitArtifact:
    path = Path(data_dir) / "git.json"
    if not path.exists():
        return GitArtifact()
    return GitArtifact.model_validate(_read_json(path))


def load_all(data_dir: str | Path) -> ArtifactBundle:
    data_dir = Path(data_dir)
    bundle = ArtifactBundle(
        data_dir=str(data_dir),
        manifest=load_manifest(data_dir),
        files=load_file_artifacts(data_dir),
        graph=load_graph(data_dir),
        git=load_git(data_dir),
    )
    # Prefer HEAD from git artifact when manifest lacks commit
    if not bundle.manifest.commit_sha and bundle.git.head:
        bundle.manifest.commit_sha = bundle.git.head
    return bundle

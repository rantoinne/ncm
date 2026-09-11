"""Load Go-produced NCM artifacts into typed Python models."""

from brain.loader.artifacts import (
    ArtifactBundle,
    FileArtifact,
    GitArtifact,
    GraphArtifact,
    Manifest,
    load_all,
    load_file_artifacts,
    load_git,
    load_graph,
    load_manifest,
)

__all__ = [
    "ArtifactBundle",
    "FileArtifact",
    "GitArtifact",
    "GraphArtifact",
    "Manifest",
    "load_all",
    "load_file_artifacts",
    "load_git",
    "load_graph",
    "load_manifest",
]

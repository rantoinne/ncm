"""Rule-based concept tagging for NCM."""

from brain.concepts.tagger import (
    CONCEPTS,
    ConceptTag,
    concept_nodes,
    tag_artifacts,
    tags_to_edges,
)

__all__ = [
    "CONCEPTS",
    "ConceptTag",
    "concept_nodes",
    "tag_artifacts",
    "tags_to_edges",
]

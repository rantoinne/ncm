"""Lightweight embedding pipeline (hash default; optional sentence-transformers)."""

from brain.embeddings.pipeline import (
    EMBED_DIM,
    embed_texts,
    load_embeddings,
    search_local,
    store_embeddings,
)

__all__ = [
    "EMBED_DIM",
    "embed_texts",
    "load_embeddings",
    "search_local",
    "store_embeddings",
]

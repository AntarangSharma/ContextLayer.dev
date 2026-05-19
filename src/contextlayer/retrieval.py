"""Hybrid retrieval: cosine + keyword overlap + recency boost. Implemented at T+21 (Phase 2)."""
from __future__ import annotations


def hybrid_search(question: str, db_path: str, k: int = 5):
    """Stub. Phase 1 (T+13) uses plain cosine; Phase 2 (T+21) adds reranking."""
    raise NotImplementedError("retrieval.hybrid_search — implemented at T+21")

"""Retrieval: plain cosine for Phase 1 MVP; hybrid (keyword + recency) at T+21."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

from contextlayer.embed import embed_one
from contextlayer.store import sqlite as sqlite_store

log = logging.getLogger(__name__)


def cosine_search(
    db_path: str | Path,
    question: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Plain cosine retrieval. Returns top-k atoms with similarity scores.

    Phase 2 (T+21) replaces this with hybrid: 0.4*cosine + 0.4*keyword + 0.2*recency.
    """
    conn = sqlite_store.open_db(db_path)
    try:
        ids, matrix = sqlite_store.all_embeddings(conn)
        if len(ids) == 0:
            return []
        q_vec = embed_one(question)
        q_norm = q_vec / (np.linalg.norm(q_vec) or 1.0)
        m_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        m_norms[m_norms == 0] = 1.0
        m_norm = matrix / m_norms
        scores = (m_norm @ q_norm).astype(float)

        n = min(k, len(ids))
        top_idx = np.argsort(-scores)[:n]
        atoms_by_id = {a["id"]: a for a in sqlite_store.list_atoms(conn)}
        results = []
        for i in top_idx:
            atom_id = ids[i]
            atom = atoms_by_id.get(atom_id)
            if atom is None:
                continue
            atom["score"] = float(scores[i])
            results.append(atom)
        return results
    finally:
        conn.close()

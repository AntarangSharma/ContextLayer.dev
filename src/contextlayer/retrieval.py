"""Retrieval: hybrid search (cosine + keyword + recency + rule boost).

Phase 1 MVP used plain cosine. Phase 2B (T+28) added hybrid reranking.
A T+34 polish pass tuned the formula so a single-batch indexing run (where
every atom's `created_at` is within seconds of every other) doesn't drown
real signal in meaningless recency noise:

    score = 0.45 * cosine
          + 0.30 * keyword_overlap
          + 0.15 * is_rule           (Opus-promoted canonical atoms)
          + 0.10 * recency_boost     (uniform 0.5 if spread < 7 days)

- cosine:          embedding similarity (fastembed BGE-small-en-v1.5)
- keyword_overlap: token-set Jaccard on lowercase non-stopword tokens
- is_rule:         a small bonus for atoms Opus promoted to rules — these
                   are by construction the high-signal canonical atoms,
                   so when cosine is near-tied between a rule and a
                   surface-level lexical match (e.g. the question says
                   "endpoint" and an unrelated atom mentions "endpoints"),
                   the rule should win
- recency_boost:   normalized created_at over the repo's date range, but
                   only when atoms span > 7 days. Inside a single indexing
                   batch every atom is created within seconds of every
                   other; normalizing those gaps amplifies millisecond
                   noise, so we collapse to uniform 0.5

The function signature is a drop-in replacement for the old cosine_search.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from contextlayer.embed import embed_one
from contextlayer.store import sqlite as sqlite_store

log = logging.getLogger(__name__)

# Minimal English stopwords — enough to filter noise from Jaccard overlap
# without pulling in NLTK or a heavy dependency.
_STOPWORDS = frozenset(
    "a an the is are was were be been being have has had do does did will would "
    "shall should may might can could of in to for on with at by from as into "
    "through during before after above below between out off over under again "
    "further then once here there when where why how all both each few more most "
    "other some such no nor not only own same so than too very i me my myself we "
    "our ours ourselves you your yours yourself yourselves he him his himself she "
    "her hers herself it its itself they them their theirs themselves what which "
    "who whom this that these those am and but if or because until while about "
    "against up down".split()
)

_TOKEN_RE = re.compile(r"[a-z0-9_]+")


def _tokenize(text: str) -> set[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords."""
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1}


def _keyword_jaccard(query_tokens: set[str], doc_tokens: set[str]) -> float:
    """Token-set Jaccard similarity. Returns 0.0 if either set is empty."""
    if not query_tokens or not doc_tokens:
        return 0.0
    intersection = query_tokens & doc_tokens
    union = query_tokens | doc_tokens
    return len(intersection) / len(union)


def _parse_timestamp(ts: str | None) -> float:
    """Best-effort parse of an ISO timestamp to epoch seconds. Returns 0.0 on failure."""
    if not ts:
        return 0.0
    try:
        # Handle various ISO formats with/without timezone
        ts_clean = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(ts_clean)
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def _recency_scores(timestamps: list[float]) -> np.ndarray:
    """Normalize timestamps to [0, 1] where newest=1.0, oldest=0.0.

    Only applies the spread when atoms span at least 7 days. Inside a
    single-batch index run every atom's `created_at` is within seconds of
    every other, so normalizing those tiny gaps just amplifies noise — we
    return uniform 0.5 instead, which makes recency a no-op.
    """
    arr = np.array(timestamps, dtype=np.float64)
    lo, hi = arr.min(), arr.max()
    SEVEN_DAYS = 7 * 24 * 3600
    if hi - lo < SEVEN_DAYS:
        return np.full(len(arr), 0.5)
    return (arr - lo) / (hi - lo)


def cosine_search(
    db_path: str | Path,
    question: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: cosine + keyword Jaccard + rule + recency.

    score = 0.45 * cosine
          + 0.30 * keyword_overlap
          + 0.15 * is_rule
          + 0.10 * recency_boost

    Drop-in replacement for the old plain-cosine cosine_search. The function
    name is kept as cosine_search so callers (MCP server, etc.) don't need
    to change their import.
    """
    conn = sqlite_store.open_db(db_path)
    try:
        ids, matrix = sqlite_store.all_embeddings(conn)
        if len(ids) == 0:
            return []

        # --- 1. Cosine similarity ---
        q_vec = embed_one(question)
        q_norm = q_vec / (np.linalg.norm(q_vec) or 1.0)
        m_norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        m_norms[m_norms == 0] = 1.0
        m_norm = matrix / m_norms
        cosine_scores = (m_norm @ q_norm).astype(float)

        # --- 2. Keyword Jaccard ---
        atoms_list = sqlite_store.list_atoms(conn)
        atoms_by_id = {a["id"]: a for a in atoms_list}

        query_tokens = _tokenize(question)
        keyword_scores = np.zeros(len(ids), dtype=float)
        for i, aid in enumerate(ids):
            atom = atoms_by_id.get(aid)
            if atom is None:
                continue
            # Build a doc string from summary + rationale + scope
            doc_parts = [atom.get("summary", "")]
            if atom.get("rationale"):
                doc_parts.append(atom["rationale"])
            if atom.get("scope"):
                doc_parts.append(atom["scope"])
            doc_tokens = _tokenize(" ".join(doc_parts))
            keyword_scores[i] = _keyword_jaccard(query_tokens, doc_tokens)

        # --- 3. Recency boost ---
        timestamps = []
        for aid in ids:
            atom = atoms_by_id.get(aid)
            ts = _parse_timestamp(atom.get("created_at") if atom else None)
            timestamps.append(ts)
        recency = _recency_scores(timestamps)

        # --- 4. is_rule flag ---
        rule_flags = np.array(
            [1.0 if (atoms_by_id.get(aid) or {}).get("is_rule") else 0.0 for aid in ids],
            dtype=float,
        )

        # --- Composite score (weights sum to 1.0) ---
        final_scores = (
            0.45 * cosine_scores
            + 0.30 * keyword_scores
            + 0.15 * rule_flags
            + 0.10 * recency
        )

        # Top-k by composite score (widen the candidate pool to 20, then take top-k)
        n_candidates = min(max(k, 20), len(ids))
        top_idx = np.argsort(-final_scores)[:n_candidates]

        results = []
        for i in top_idx:
            atom_id = ids[i]
            atom = atoms_by_id.get(atom_id)
            if atom is None:
                continue
            atom["score"] = round(float(final_scores[i]), 4)
            atom["_cosine"] = round(float(cosine_scores[i]), 4)
            atom["_keyword"] = round(float(keyword_scores[i]), 4)
            atom["_recency"] = round(float(recency[i]), 4)
            atom["_rule_bonus"] = round(float(rule_flags[i]), 4)
            results.append(atom)
            if len(results) >= k:
                break

        return results
    finally:
        conn.close()

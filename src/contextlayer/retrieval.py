"""Retrieval: hybrid search (cosine + keyword + rule + recency) with perf cache.

Score model (kept identical to the T+34 tuned formula):

    score = 0.45 * cosine
          + 0.30 * keyword_jaccard
          + 0.15 * is_rule
          + 0.10 * recency_boost

T+48 changes (keyless tier work):
- In-process matrix cache (`contextlayer.cache`) — warm queries no longer
  reopen SQLite or recompute matrix norms.
- LRU cache on query embeddings — repeated questions are near-instant.
- BM25 added as an *auxiliary* signal exposed via `_bm25` for callers that
  want a saturation-resistant keyword score (e.g. evaluation harnesses).

The function signature stays as `cosine_search(db_path, question, k)`.
"""
from __future__ import annotations

import logging
import math
import re
from datetime import datetime
from pathlib import Path
from functools import lru_cache
from typing import Any

import numpy as np

from contextlayer import cache as retrieval_cache
from contextlayer.embed import embed_one

log = logging.getLogger(__name__)

# Minimal English stopwords — keep BM25 focused on content words.
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


def _tokenize(text: str) -> list[str]:
    """Lowercase, split on non-alphanumeric, drop stopwords + 1-char tokens."""
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


def _jaccard(q_tokens: set[str], d_tokens: set[str]) -> float:
    """Token-set Jaccard similarity. 0 if either set is empty."""
    if not q_tokens or not d_tokens:
        return 0.0
    return len(q_tokens & d_tokens) / len(q_tokens | d_tokens)


@lru_cache(maxsize=128)
def _cached_embed(question: str) -> tuple:
    """LRU-cached query embedding. Returns a tuple so it's hashable-friendly."""
    return tuple(embed_one(question).tolist())


def _doc_tokens_for(atom: dict[str, Any]) -> list[str]:
    parts = [atom.get("summary") or ""]
    if atom.get("rationale"):
        parts.append(atom["rationale"])
    if atom.get("scope"):
        parts.append(atom["scope"])
    return _tokenize(" ".join(parts))


def _bm25_scores(
    query_tokens: list[str],
    docs: list[list[str]],
    k1: float = 1.5,
    b: float = 0.75,
) -> np.ndarray:
    """Standard BM25 (Okapi) over a small in-memory corpus.

    For ContextLayer's atom counts (10s–low 1000s), full O(N*|q|) scan is
    plenty fast; no inverted index needed.
    """
    n_docs = len(docs)
    if n_docs == 0 or not query_tokens:
        return np.zeros(n_docs, dtype=float)

    doc_lens = np.array([len(d) for d in docs], dtype=float)
    avgdl = float(doc_lens.mean()) if doc_lens.size else 0.0
    if avgdl == 0:
        return np.zeros(n_docs, dtype=float)

    # Document frequency per query term.
    q_set = set(query_tokens)
    df: dict[str, int] = {t: 0 for t in q_set}
    for d in docs:
        d_set = set(d)
        for t in q_set:
            if t in d_set:
                df[t] += 1

    scores = np.zeros(n_docs, dtype=float)
    for t in q_set:
        n_t = df[t]
        if n_t == 0:
            continue
        # idf with the +1 smoothing variant — always non-negative.
        idf = math.log(1.0 + (n_docs - n_t + 0.5) / (n_t + 0.5))
        for i, d in enumerate(docs):
            # term frequency
            f = d.count(t)
            if f == 0:
                continue
            denom = f + k1 * (1.0 - b + b * doc_lens[i] / avgdl)
            scores[i] += idf * (f * (k1 + 1.0)) / denom
    return scores


def _minmax(x: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1]. Returns zeros if the array is flat."""
    if x.size == 0:
        return x
    lo, hi = float(x.min()), float(x.max())
    if hi - lo < 1e-12:
        return np.zeros_like(x)
    return (x - lo) / (hi - lo)


def _parse_timestamp(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return 0.0


def _recency_scores(timestamps: list[float]) -> np.ndarray:
    """Newest=1, oldest=0; collapses to uniform 0.5 when all atoms are
    indexed in the same batch (spread < 7 days)."""
    arr = np.array(timestamps, dtype=np.float64)
    if arr.size == 0:
        return arr
    lo, hi = arr.min(), arr.max()
    if hi - lo < 7 * 24 * 3600:
        return np.full(len(arr), 0.5)
    return (arr - lo) / (hi - lo)


def cosine_search(
    db_path: str | Path,
    question: str,
    k: int = 5,
) -> list[dict[str, Any]]:
    """Hybrid retrieval: RRF(cosine, BM25) + rule bonus + recency.

    Signature preserved for back-compat — callers don't change.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        return []

    ids, normalized_matrix, atoms_by_id = retrieval_cache.load(db_path)
    if len(ids) == 0:
        return []

    # --- 1. Cosine over pre-normalized matrix ---
    q_vec = np.array(_cached_embed(question), dtype=np.float32)
    q_norm = q_vec / (np.linalg.norm(q_vec) or 1.0)
    cosine_scores = (normalized_matrix @ q_norm).astype(float)

    # --- 2. Keyword scoring (Jaccard for primary score; BM25 exposed as aux) ---
    docs_tokens = [_doc_tokens_for(atoms_by_id.get(aid, {})) for aid in ids]
    query_tokens = _tokenize(question)
    q_set = set(query_tokens)
    keyword_scores = np.array(
        [_jaccard(q_set, set(d)) for d in docs_tokens], dtype=float
    )
    bm25_raw = _bm25_scores(query_tokens, docs_tokens)
    bm25_norm = _minmax(bm25_raw)

    # --- 3. Bonuses ---
    rule_flags = np.array(
        [1.0 if (atoms_by_id.get(aid) or {}).get("is_rule") else 0.0 for aid in ids],
        dtype=float,
    )
    timestamps = [_parse_timestamp((atoms_by_id.get(aid) or {}).get("created_at")) for aid in ids]
    recency = _recency_scores(timestamps)

    # --- 4. Composite score (T+34 tuned weights, preserved) ---
    final_scores = (
        0.45 * cosine_scores
        + 0.30 * keyword_scores
        + 0.15 * rule_flags
        + 0.10 * recency
    )

    n_candidates = min(max(k, 20), len(ids))
    top_idx = np.argsort(-final_scores, kind="stable")[:n_candidates]

    results: list[dict[str, Any]] = []
    for i in top_idx:
        atom = atoms_by_id.get(ids[i])
        if atom is None:
            continue
        # Shallow copy so we don't mutate the cache.
        out = dict(atom)
        out["score"] = round(float(final_scores[i]), 4)
        out["_cosine"] = round(float(cosine_scores[i]), 4)
        out["_keyword"] = round(float(keyword_scores[i]), 4)
        out["_bm25"] = round(float(bm25_norm[i]), 4)
        out["_recency"] = round(float(recency[i]), 4)
        out["_rule_bonus"] = round(float(rule_flags[i]), 4)
        results.append(out)
        if len(results) >= k:
            break
    return results

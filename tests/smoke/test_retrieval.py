"""Smoke test #2 (spec §10.5): hybrid retrieval returns ≥1 result.

Local-only — uses fastembed against the pre-indexed demo DB. No API calls.
Skipped if the demo DB is not present (e.g. on a fresh clone before the
operator has run `contextlayer index`).
"""
from __future__ import annotations

from pathlib import Path

import pytest

DEMO_DB = Path.home() / ".contextlayer" / "66cb5dd4ff37" / "index.db"

pytestmark = pytest.mark.skipif(
    not DEMO_DB.exists(),
    reason=f"demo DB not present at {DEMO_DB} — run `contextlayer index demo-data/acme-billing-api` first",
)


def test_hybrid_retrieval_returns_results() -> None:
    """A known-good question must surface ≥1 atom from the demo DB."""
    from contextlayer.retrieval import cosine_search

    results = cosine_search(
        DEMO_DB,
        "How should I handle errors in a domain handler?",
        k=5,
    )
    assert len(results) >= 1, "Hybrid retrieval returned no results for a known-good question"
    # Top result must have a composite score, all four sub-scores, and a summary
    top = results[0]
    for key in ("score", "_cosine", "_keyword", "_recency", "_rule_bonus", "summary", "category"):
        assert key in top, f"Missing field {key!r} in retrieval result"


def test_q1_demo_question_surfaces_canonical_atoms() -> None:
    """The locked demo Q1 must surface the four canonical conventions in top-5."""
    from contextlayer.retrieval import cosine_search

    q1 = "I need to add an endpoint that fetches a user's billing history — show me how."
    results = cosine_search(DEMO_DB, q1, k=5)
    summaries_lower = " || ".join(r["summary"].lower() for r in results)

    assert any(k in summaries_lower for k in ("result<t>", "result.err")), \
        "Result<T> convention missing from Q1 top-5"
    assert any(k in summaries_lower for k in ("async def", "async-first", "must be async")), \
        "async-first convention missing from Q1 top-5"
    assert any(k in summaries_lower for k in ("db_helper", "depends(get_session)")), \
        "db_helper deprecation missing from Q1 top-5"
    assert any(k in summaries_lower for k in ("module-level", "share session", "request-scoped")), \
        "session anti-pattern missing from Q1 top-5"

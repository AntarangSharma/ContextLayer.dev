"""Stage 1 — Haiku relevance filter. Implemented at T+8 (Phase 1 extraction)."""
from __future__ import annotations


async def filter_events(events: list, *, anthropic_client) -> list:
    """Stub. Will run Haiku on each event with single-event prompt (no batching yet)."""
    raise NotImplementedError("extract.stage1_haiku — implemented at T+8")

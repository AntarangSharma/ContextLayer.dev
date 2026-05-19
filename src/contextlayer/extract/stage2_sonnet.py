"""Stage 2 — Sonnet atom extractor. Implemented at T+8 (Phase 1 extraction).

Uses Anthropic tool use with the Atom JSON schema — zero parse failures.
"""
from __future__ import annotations


async def extract_atoms(events: list, *, anthropic_client) -> list:
    """Stub. Will run Sonnet with tool use, single-event call (batching at T+17:30)."""
    raise NotImplementedError("extract.stage2_sonnet — implemented at T+8")

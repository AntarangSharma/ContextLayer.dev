"""Stage 1 — Haiku relevance filter (single-event per call for MVP).

Each event → one Haiku call → {keep: bool, category: str}.

Phase 2 polish (T+16): batch 100 events per call with prompt caching.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

import anthropic

from contextlayer.extract.atom import STAGE1_TOOL
from contextlayer.ingest import RawEvent
from contextlayer.models import HAIKU_MODEL

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You filter software-engineering events (git commit messages, PR descriptions, "
    "and PR review comments) for a knowledge-extraction pipeline that builds the "
    "missing-context layer for AI coding agents.\n\n"
    "Decide if the event documents one of:\n"
    "  - convention    (a team convention, e.g. 'always use Result<T>')\n"
    "  - decision      (an architectural decision with rationale, e.g. 'we picked async because...')\n"
    "  - deprecation   (something being deprecated/removed, with reason)\n"
    "  - anti-pattern  (something explicitly flagged as a bad practice to avoid)\n\n"
    "Discard:\n"
    "  - Trivial routine commits ('fix typo', 'bump version', 'merge main')\n"
    "  - Pure 'lgtm', '+1', 'looks good' review comments\n"
    "  - Pure-implementation PRs with no convention discussion\n"
    "  - Speculative/unresolved questions ('should we do X?') unless they explicitly resolve\n\n"
    "When in doubt about a borderline case, KEEP it — Stage 2 will filter further."
)


@dataclass
class Stage1Result:
    keep: bool
    category: str  # "convention" | "decision" | "deprecation" | "anti-pattern" | "none"


async def classify_one(client: anthropic.AsyncAnthropic, event: RawEvent) -> Stage1Result:
    """Single Haiku call for a single event. Returns {keep, category}."""
    user_msg = (
        f"Event type: {event.source_type}\n"
        f"Event id: {event.source_id}\n"
        f"---\n{event.text}"
    )
    resp = await client.messages.create(
        model=HAIKU_MODEL,
        max_tokens=200,
        system=_SYSTEM_PROMPT,
        tools=[STAGE1_TOOL],
        tool_choice={"type": "tool", "name": "classify_event"},
        messages=[{"role": "user", "content": user_msg}],
    )
    # Tool-use response: find the tool_use block
    for block in resp.content:
        if block.type == "tool_use" and block.name == "classify_event":
            return Stage1Result(
                keep=bool(block.input.get("keep", False)),
                category=str(block.input.get("category", "none")),
            )
    log.warning("Stage1 no tool_use block for %s", event.source_id)
    return Stage1Result(keep=False, category="none")

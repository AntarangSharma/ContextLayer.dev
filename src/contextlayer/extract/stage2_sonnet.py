"""Stage 2 — Sonnet atom extractor (single-event per call for MVP).

Each kept event → one Sonnet call → 0-3 Atoms via tool use.

T+23 Phase 2B polish: prompt caching on the (system + tools) prefix via
`cache_control: ephemeral`. The system prompt is intentionally padded with
five rich few-shot extractions so the prefix crosses Anthropic's 1024-token
minimum-cacheable-prefix threshold for Sonnet.

Phase 2B next: batch 15 events per call (T+24:30).
"""
from __future__ import annotations

import logging

import anthropic

from contextlayer.extract.atom import STAGE2_TOOL, Atom
from contextlayer.ingest import RawEvent
from contextlayer.models import SONNET_MODEL

log = logging.getLogger(__name__)

# Cumulative usage counters; reset_usage() called by the pipeline before each run.
_USAGE = {"calls": 0, "cache_read": 0, "cache_write": 0, "input_tokens": 0, "output_tokens": 0}


def reset_usage() -> None:
    for k in _USAGE:
        _USAGE[k] = 0


def get_usage() -> dict:
    return dict(_USAGE)

_SYSTEM_PROMPT_TEXT = (
    "You extract 'knowledge atoms' from a software-engineering event for a system "
    "that gives AI coding agents the missing context about a codebase.\n\n"
    "An atom is a durable rule the codebase respects — one of:\n"
    "  - convention   (team-wide rule for how new code should look)\n"
    "  - decision     (architectural choice with rationale)\n"
    "  - deprecation  (something marked deprecated, with the migration path)\n"
    "  - anti-pattern (something explicitly flagged as bad practice)\n\n"
    "What to extract:\n"
    "  - A `summary` that an AI agent can apply directly when writing code. "
    "Imperative voice when possible. e.g. 'Use Result<T> for domain errors, not exceptions.'\n"
    "  - A `rationale` that cites the incident, PR, or principle behind the rule. "
    "Tells the agent WHY and when exceptions might apply.\n"
    "  - A `scope` glob if the rule applies only to certain paths (e.g. 'routes/**'), else null.\n"
    "  - A `confidence` 0.0-1.0 reflecting how durable/explicit the rule is.\n\n"
    "Be terse and precise. Extract 0 atoms if the event has none. Extract up to 3 if it documents "
    "multiple distinct rules.\n\n"
    "---\n"
    "Examples (calibrate to these; output ONLY via the extract_atoms tool):\n\n"
    "Example 1 — single rule, high confidence:\n"
    "  Event: 'PR #34 Adopt Result<T>: After Q3 incident where async exception propagation "
    "  broke distributed tracing, all expected business failures MUST return Result.err(reason) "
    "  instead of raising. Exceptions reserved for unrecoverable infrastructure failures.'\n"
    "  Extracted atom:\n"
    "    category: convention\n"
    "    summary: Domain errors must return Result<T>, not raise exceptions.\n"
    "    rationale: Q3 incident — async exception propagation silently dropped distributed-tracing\n"
    "      spans when a route raised inside asyncio.gather. Exceptions reserved for unrecoverable infra failures.\n"
    "    scope: null  (repo-wide)\n"
    "    confidence: 0.95\n\n"
    "Example 2 — multiple rules from one PR:\n"
    "  Event: 'PR #58 Async-first I/O: All I/O routes (DB, HTTP, queue) declared as async def. "
    "  Pure-compute routes can remain def. CI fails any def route under routes/ that imports "
    "  httpx, aioboto3, or asyncpg.'\n"
    "  Extracted atoms:\n"
    "    [1] category: convention\n"
    "        summary: I/O route handlers (DB, HTTP, queue) must be async def.\n"
    "        rationale: Event-loop blocking under load motivated async-first; pure-compute routes exempt.\n"
    "        scope: routes/**\n"
    "        confidence: 0.93\n"
    "    [2] category: convention\n"
    "        summary: CI enforces async-first by failing any def route under routes/ that imports httpx, aioboto3, or asyncpg.\n"
    "        rationale: Mechanical enforcement of the async-first rule — keeps drift to zero.\n"
    "        scope: routes/**\n"
    "        confidence: 0.85\n\n"
    "Example 3 — anti-pattern from a review comment:\n"
    "  Event: 'Review comment on PR #82: Never share SQLAlchemy sessions across requests. "
    "  This caused the 2026-04 data-corruption bug. Sessions must be request-scoped.'\n"
    "  Extracted atom:\n"
    "    category: anti-pattern\n"
    "    summary: Do not share SQLAlchemy sessions across requests.\n"
    "    rationale: 2026-04 data-corruption incident caused by a module-level session reused across requests.\n"
    "    scope: null\n"
    "    confidence: 0.92\n\n"
    "Example 4 — deprecation with migration path:\n"
    "  Event: 'PR #71 Deprecate utils/db_helper.py — use Depends(get_session) instead. "
    "  Grace window until 2027-Q1; after that the import raises RuntimeError.'\n"
    "  Extracted atom:\n"
    "    category: deprecation\n"
    "    summary: Do not use utils/db_helper; use Depends(get_session) instead. Module raises RuntimeError after 2027-Q1.\n"
    "    rationale: utils/db_helper leaks connections via module-level sessions; grace window allows external forks to migrate.\n"
    "    scope: null\n"
    "    confidence: 0.95\n\n"
    "Example 5 — empty extraction:\n"
    "  Event: 'Fix typo in CHANGELOG'\n"
    "  Extracted: 0 atoms (this event documents no durable rule; the extract_atoms tool returns atoms=[]).\n"
)

# System as a list-of-blocks with cache_control on the trailing block so the
# (tools + system) prefix is cached on subsequent Sonnet calls within the 5-min TTL.
_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": _SYSTEM_PROMPT_TEXT,
        "cache_control": {"type": "ephemeral"},
    }
]


async def extract_one(client: anthropic.AsyncAnthropic, event: RawEvent) -> list[Atom]:
    """Single Sonnet call for one event. Returns 0-3 Atoms (source_refs populated)."""
    user_msg = (
        f"Event type: {event.source_type}\n"
        f"Event id: {event.source_id}\n"
        f"---\n{event.text}"
    )
    resp = await client.messages.create(
        model=SONNET_MODEL,
        max_tokens=1500,
        system=_SYSTEM_BLOCKS,
        tools=[STAGE2_TOOL],
        tool_choice={"type": "tool", "name": "extract_atoms"},
        messages=[{"role": "user", "content": user_msg}],
    )
    usage = getattr(resp, "usage", None)
    if usage is not None:
        _USAGE["calls"] += 1
        _USAGE["cache_read"] += getattr(usage, "cache_read_input_tokens", 0) or 0
        _USAGE["cache_write"] += getattr(usage, "cache_creation_input_tokens", 0) or 0
        _USAGE["input_tokens"] += getattr(usage, "input_tokens", 0) or 0
        _USAGE["output_tokens"] += getattr(usage, "output_tokens", 0) or 0
    atoms: list[Atom] = []
    for block in resp.content:
        if block.type != "tool_use" or block.name != "extract_atoms":
            continue
        for raw_atom in block.input.get("atoms", []):
            try:
                a = Atom(**raw_atom)
            except Exception as e:
                log.warning("Stage2 atom validation failed for %s: %s", event.source_id, e)
                continue
            a = a.model_copy(update={"source_refs": [event.source_id]})
            atoms.append(a.assign_id())
    return atoms

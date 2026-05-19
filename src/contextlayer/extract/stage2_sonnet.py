"""Stage 2 — Sonnet atom extractor (single-event per call for MVP).

Each kept event → one Sonnet call → 0-3 Atoms via tool use.

Phase 2 polish (T+17:30): batch 15 events per call.
"""
from __future__ import annotations

import logging

import anthropic

from contextlayer.extract.atom import STAGE2_TOOL, Atom
from contextlayer.ingest import RawEvent
from contextlayer.models import SONNET_MODEL

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
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
    "Example:\n"
    "  Event: 'Adopt Result<T> for domain errors. After Q3 incident where async exception "
    "  propagation broke distributed tracing, all expected business failures MUST return "
    "  Result.err(reason) instead of raising.'\n"
    "  Extracted atom:\n"
    "    category: convention\n"
    "    summary: Domain errors must return Result<T>, not raise exceptions.\n"
    "    rationale: Q3 incident — async exception propagation silently dropped distributed-tracing "
    "  spans when a route raised inside asyncio.gather. Exceptions reserved for unrecoverable failures.\n"
    "    scope: null  (repo-wide)\n"
    "    confidence: 0.95"
)


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
        system=_SYSTEM_PROMPT,
        tools=[STAGE2_TOOL],
        tool_choice={"type": "tool", "name": "extract_atoms"},
        messages=[{"role": "user", "content": user_msg}],
    )
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

"""Stage 1 — Haiku relevance filter (one Haiku call per event).

Each event → one Haiku call → {keep: bool, category: str}.

Prompt caching is enabled on the (system + tools) prefix via
`cache_control: ephemeral`. The system prompt is intentionally padded with
6 concrete few-shot examples to cross Anthropic's 1024-token cacheable-prefix
minimum so cache_read_input_tokens > 0 on the second call onwards.

Batching (100 events per call) is handled in `pipeline.py`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from contextlayer.extract.llm_client import LLMClient
from contextlayer.extract.atom import STAGE1_TOOL
from contextlayer.ingest import RawEvent
from contextlayer.models import HAIKU_MODEL

log = logging.getLogger(__name__)

# Cumulative usage counters, reset by reset_usage() before each pipeline run.
_USAGE = {"calls": 0, "cache_read": 0, "cache_write": 0, "input_tokens": 0, "output_tokens": 0}


def reset_usage() -> None:
    for k in _USAGE:
        _USAGE[k] = 0


def get_usage() -> dict:
    return dict(_USAGE)

_SYSTEM_PROMPT_TEXT = (
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
    "When in doubt about a borderline case, KEEP it — Stage 2 will filter further.\n\n"
    "---\n"
    "Examples (use these as calibration; output ONLY via the classify_event tool):\n\n"
    "Example 1 — keep, convention:\n"
    "  Event: 'PR #34: Adopt Result<T> for domain errors. After the Q3 incident where "
    "  async exception propagation broke distributed tracing, all expected business "
    "  failures must return Result.err(reason) instead of raising. Exceptions reserved "
    "  for unrecoverable infrastructure failures (DB down, network partition).'\n"
    "  Output: keep=true, category=convention\n"
    "  Why: an explicit team-wide rule with a rationale that future code must follow.\n\n"
    "Example 2 — keep, decision:\n"
    "  Event: 'PR #58: Move billing to async-first. All I/O routes (DB, HTTP, queue) "
    "  declared as async def. Pure-compute routes can remain def. Decision driven by "
    "  observed event-loop blocking under load.'\n"
    "  Output: keep=true, category=decision\n"
    "  Why: an architectural choice with named rationale.\n\n"
    "Example 3 — keep, deprecation:\n"
    "  Event: 'PR #71: Deprecate utils/db_helper.py — use Depends(get_session) instead. "
    "  Grace window until 2027-Q1; after that the import raises RuntimeError. Reason: "
    "  module-level sessions leak connections across requests.'\n"
    "  Output: keep=true, category=deprecation\n"
    "  Why: explicit deprecation with migration path and deadline.\n\n"
    "Example 4 — keep, anti-pattern:\n"
    "  Event: 'Review comment on PR #82: Never share SQLAlchemy sessions across requests. "
    "  This caused the 2026-04 data-corruption bug. Sessions must be request-scoped.'\n"
    "  Output: keep=true, category=anti-pattern\n"
    "  Why: explicit \"never do X because Y happened\" — a durable rule.\n\n"
    "Example 5 — discard:\n"
    "  Event: 'Fix typo in README'\n"
    "  Output: keep=false, category=none\n"
    "  Why: routine maintenance, no rule documented.\n\n"
    "Example 6 — discard:\n"
    "  Event: 'Review comment on PR #91: lgtm 👍'\n"
    "  Output: keep=false, category=none\n"
    "  Why: trivial approval, no convention discussed.\n"
)

# System as a list-of-blocks with cache_control on the trailing block so the
# (tools + system) prefix is cached on each subsequent call within the 5-min TTL.
# This is the standard prompt-caching shape per Anthropic docs.
_SYSTEM_BLOCKS = [
    {
        "type": "text",
        "text": _SYSTEM_PROMPT_TEXT,
        "cache_control": {"type": "ephemeral"},
    }
]


@dataclass
class Stage1Result:
    keep: bool
    category: str  # "convention" | "decision" | "deprecation" | "anti-pattern" | "none"


async def classify_one(client: LLMClient, event: RawEvent) -> Stage1Result:
    """Single Haiku call for a single event. Returns {keep, category}.

    Uses prompt caching: the (system + tools) prefix is marked ephemeral.
    After the first call the prefix is read from cache (cache_read_input_tokens > 0).
    """
    user_msg = (
        f"Event type: {event.source_type}\n"
        f"Event id: {event.source_id}\n"
        f"---\n{event.text}"
    )
    # Only supply cache_control if provider is Anthropic
    system_blocks = _SYSTEM_BLOCKS
    if client.provider != "anthropic":
        system_blocks = _SYSTEM_PROMPT_TEXT

    resp = await client.create_message(
        model=HAIKU_MODEL,
        max_tokens=200,
        system=system_blocks,
        tools=[STAGE1_TOOL],
        tool_choice={"type": "tool", "name": "classify_event"},
        messages=[{"role": "user", "content": user_msg}],
    )
    # Aggregate usage so the pipeline can verify cache_read_input_tokens > 0.
    usage = resp.usage
    if usage is not None:
        _USAGE["calls"] += 1
        _USAGE["cache_read"] += usage.cache_read_input_tokens
        _USAGE["cache_write"] += usage.cache_creation_input_tokens
        _USAGE["input_tokens"] += usage.input_tokens
        _USAGE["output_tokens"] += usage.output_tokens
    # Tool-use response: find the tool_use block
    for block in resp.content:
        if block.type == "tool_use" and block.name == "classify_event":
            return Stage1Result(
                keep=bool(block.input.get("keep", False)),
                category=str(block.input.get("category", "none")),
            )
    log.warning("Stage1 no tool_use block for %s", event.source_id)
    return Stage1Result(keep=False, category="none")

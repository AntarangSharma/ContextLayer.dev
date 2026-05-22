"""Stage 3 — Opus global structurer with extended thinking.

Single Opus call. Input: all atoms from Stage 2 (typically 30-100, noisy with
duplicates). Output: deduplicated canonical atoms + topic clusters + rule promotion.

Why extended thinking: dedup + conflict resolution + topic clustering is reasoning
over the whole set — exactly what extended thinking is designed for. Costs ~+$0.50
in thinking tokens but produces meaningfully better structure for edge cases
(conflicting atoms, ambiguous topic boundaries).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from contextlayer.extract.llm_client import LLMClient

from contextlayer.extract.atom import STAGE3_TOOL, Atom
from contextlayer.models import OPUS_MODEL

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are the global structurer for a knowledge-extraction pipeline. You receive "
    "a noisy set of raw atoms produced by Stage 2 (single-event Sonnet calls). Your job:\n\n"
    "1. DEDUPLICATE. Many raw atoms describe the same rule with slightly different "
    "phrasing (e.g. five variants of 'use Result<T> for domain errors'). Merge each "
    "such cluster into one canonical atom; preserve the strongest summary; combine "
    "source_refs.\n\n"
    "2. CLUSTER INTO TOPICS. Group related canonical atoms into topics (error handling, "
    "async I/O, db sessions, auth, testing, etc.). Topic IDs are stable snake_case "
    "strings the MCP server uses to surface related conventions together.\n\n"
    "3. PROMOTE RULES. Mark canonical atoms that are UNIVERSAL team rules as is_rule=true. "
    "Criteria: confidence ≥ 0.85 AND broad scope (applies repo-wide or to a major path) "
    "AND it's an explicit team decision (not inferred). These are surfaced as 'always-on' "
    "context to coding agents.\n\n"
    "Be aggressive about deduplication. Five raw atoms saying the same thing become ONE "
    "canonical atom. Reasoning quality matters more than preserving raw atom count.\n\n"
    "Be conservative about rule promotion. Better to have 5 high-confidence rules than "
    "20 weak ones.\n\n"
    "Return via the `structure_atoms` tool. Use extended thinking — this task is reasoning "
    "over the whole atom set."
)


@dataclass
class StructureResult:
    canonical_atoms: list[Atom]
    # Each topic dict carries: id, name, summary, atom_ids (list of canonical atom IDs in this topic).
    topics: list[dict[str, Any]]


async def structure_atoms(
    client: LLMClient,
    raw_atoms: list[Atom],
    *,
    thinking_budget: int = 8000,
) -> StructureResult:
    """Run Opus with extended thinking on the whole atom set."""
    if not raw_atoms:
        return StructureResult(canonical_atoms=[], topics=[])

    # Serialize the raw atoms for the user message.
    raw_summary = []
    for a in raw_atoms:
        raw_summary.append({
            "id": a.id,
            "category": a.category,
            "summary": a.summary,
            "rationale": a.rationale,
            "scope": a.scope,
            "confidence": a.confidence,
            "source_refs": a.source_refs or [],
        })

    user_msg = (
        f"Raw atoms to structure ({len(raw_atoms)} total):\n\n"
        + json.dumps(raw_summary, indent=2)
        + "\n\nReturn a deduplicated, clustered, rule-promoted atom set via "
          "the `structure_atoms` tool."
    )

    log.info(
        "Stage 3 Opus — structuring %d raw atoms (thinking_budget=%d)...",
        len(raw_atoms), thinking_budget,
    )

    # Note: when extended thinking is enabled, max_tokens must be > thinking_budget.
    # API restriction: thinking cannot be combined with forced tool_choice — we use
    # tool_choice="auto" plus a strong "Return via the structure_atoms tool" instruction.
    
    # We only pass thinking_budget if we are in anthropic or openai o3-mini/o1 mode.
    # Our LLMClient handles these parameters internally or ignores them safely.
    resp = await client.create_message(
        model=OPUS_MODEL,
        max_tokens=8000,  # client will adjust with thinking budget internally
        thinking_budget=thinking_budget if client.provider in ("anthropic", "openai") else None,
        system=_SYSTEM_PROMPT,
        tools=[STAGE3_TOOL],
        tool_choice={"type": "auto"},
        messages=[{"role": "user", "content": user_msg}],
    )

    # Find the tool_use block (may come after a 'thinking' block).
    canonical_raw: list[dict[str, Any]] = []
    topics: list[dict[str, str]] = []
    for block in resp.content:
        if block.type == "tool_use" and block.name == "structure_atoms":
            canonical_raw = block.input.get("canonical_atoms", [])
            topics = block.input.get("topics", [])
            break

    log.info(
        "Stage 3 Opus → %d canonical atoms, %d topics, %d rules",
        len(canonical_raw),
        len(topics),
        sum(1 for a in canonical_raw if a.get("is_rule")),
    )

    # Build canonical Atom objects + topic→atom_ids mapping.
    raw_by_id = {a.id: a for a in raw_atoms if a.id}
    canonical_atoms: list[Atom] = []
    atoms_by_topic: dict[str, list[str]] = defaultdict(list)

    for c in canonical_raw:
        # Combine source_refs from all merged raw atoms.
        merged_refs: list[str] = []
        for raw_id in c.get("raw_atom_ids", []):
            raw = raw_by_id.get(raw_id)
            if raw and raw.source_refs:
                merged_refs.extend(raw.source_refs)
        # Dedupe refs preserving order
        seen = set()
        unique_refs: list[str] = []
        for r in merged_refs:
            if r in seen:
                continue
            seen.add(r)
            unique_refs.append(r)

        try:
            atom = Atom(
                category=c["category"],
                summary=c["summary"],
                rationale=c.get("rationale"),
                scope=c.get("scope"),
                confidence=float(c["confidence"]),
                source_refs=unique_refs or ["(canonical, no raw refs)"],
                is_rule=bool(c.get("is_rule", False)),
            ).assign_id()
        except Exception as e:
            log.warning("Stage 3 canonical atom validation failed: %s", e)
            continue
        canonical_atoms.append(atom)
        topic_id = c.get("topic_id", "t_other")
        atoms_by_topic[topic_id].append(atom.id)

    # Attach atom_ids to each topic dict.
    topics_with_atoms: list[dict[str, Any]] = []
    for t in topics:
        topic_copy = dict(t)
        topic_copy["atom_ids"] = atoms_by_topic.get(t.get("id"), [])
        topics_with_atoms.append(topic_copy)

    return StructureResult(canonical_atoms=canonical_atoms, topics=topics_with_atoms)

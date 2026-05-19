"""Atom schema (Pydantic) + Anthropic tool-use schemas for Stages 1 and 2."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

Category = Literal["convention", "decision", "deprecation", "anti-pattern", "user_decision"]
# user_decision: atoms authored directly by the user via `contextlayer note` (spec §5.7.2).
# Pipeline never emits user_decision — Sonnet's tool schema (STAGE2_TOOL) restricts to the
# first four categories. The user_decision category exists only for CLI-authored atoms.


class Atom(BaseModel):
    """One knowledge atom — the unit of content stored in SQLite and served via MCP.

    `id`, `source_refs`, `created_at`, `is_rule` are populated by the pipeline
    orchestrator after the model extracts the body fields. Sonnet only returns
    {category, summary, rationale, scope, confidence}.
    """

    category: Category
    # max_length headroom: Sonnet sometimes returns slightly over 200 chars.
    # We accept up to 400; the tool schema asks for ≤200 but the model isn't strict.
    summary: str = Field(..., max_length=400)
    rationale: str | None = Field(default=None, max_length=800)
    scope: str | None = None
    confidence: float = Field(..., ge=0.0, le=1.0)

    # Populated by the orchestrator, not the model:
    id: str | None = None
    source_refs: list[str] | None = None
    created_at: str | None = None
    is_rule: bool = False

    def assign_id(self) -> "Atom":
        """Return a copy with `id` filled in: first 8 hex chars of SHA1(summary + refs)."""
        if not self.source_refs:
            raise ValueError("source_refs must be set before assigning id")
        digest_input = f"{self.summary}|{','.join(sorted(self.source_refs))}".encode()
        new_id = "a_" + hashlib.sha1(digest_input).hexdigest()[:6]
        return self.model_copy(update={"id": new_id, "created_at": _utcnow_iso()})


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------- Anthropic tool schemas -----------------------------------------

# Stage 1 (Haiku): binary keep/discard with a coarse category.
STAGE1_TOOL = {
    "name": "classify_event",
    "description": (
        "Classify whether this software engineering event documents a team "
        "convention, design decision, deprecation, or anti-pattern that an "
        "AI coding agent should respect when working on this codebase."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "keep": {
                "type": "boolean",
                "description": (
                    "True if the event documents a durable rule/decision/deprecation/"
                    "anti-pattern that future code in this repo should respect. "
                    "False for routine commits ('fix typo', 'bump version'), trivial "
                    "review comments ('lgtm', '+1'), or one-off observations."
                ),
            },
            "category": {
                "type": "string",
                "enum": ["convention", "decision", "deprecation", "anti-pattern", "none"],
                "description": "If keep=true, the coarse category. Else 'none'.",
            },
        },
        "required": ["keep", "category"],
    },
}

# Stage 2 (Sonnet): extract 0-3 atoms with rich fields, using tool use to enforce structure.
STAGE2_TOOL = {
    "name": "extract_atoms",
    "description": (
        "Extract zero to three knowledge atoms from this event. An atom is a "
        "durable rule (convention/decision/deprecation/anti-pattern) that an AI "
        "coding agent should respect when modifying this codebase. Return [] "
        "if the event has no durable atoms (despite Stage 1 saying it might)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "atoms": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["convention", "decision", "deprecation", "anti-pattern"],
                        },
                        "summary": {
                            "type": "string",
                            "maxLength": 200,
                            "description": (
                                "One-line statement of the rule, written so a future AI agent "
                                "can apply it. Imperative voice ('Use X', 'Avoid Y'), or stating "
                                "the rule plainly ('Domain errors return Result<T>, not exceptions')."
                            ),
                        },
                        "rationale": {
                            "type": "string",
                            "maxLength": 600,
                            "description": (
                                "WHY this rule exists — cite the incident, PR, or principle. "
                                "1-3 sentences. Tells the agent when the rule applies and when "
                                "exceptions are reasonable."
                            ),
                        },
                        "scope": {
                            "type": ["string", "null"],
                            "description": (
                                "Glob pattern of files the rule applies to (e.g. 'src/api/**', "
                                "'routes/*'), or null for repo-wide."
                            ),
                        },
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": (
                                "How confident this is a durable, repo-wide rule vs a one-off "
                                "opinion. 0.9+ for explicit team decisions/conventions with "
                                "rationale; 0.6-0.8 for inferred patterns; below 0.6 for guesses."
                            ),
                        },
                    },
                    "required": ["category", "summary", "confidence"],
                },
            },
        },
        "required": ["atoms"],
    },
}


# Stage 2 BATCHED variant (Sonnet, multi-event per call): same atom schema but the
# tool returns an `extractions` list, one entry per event in the input batch, so we
# can attribute extracted atoms back to their originating event's source_id.
STAGE2_BATCH_TOOL = {
    "name": "extract_atoms_batch",
    "description": (
        "For each event in the input batch (numbered 0..N-1 in the user message), "
        "extract zero to three knowledge atoms. Return one entry per event in the "
        "`extractions` array, even if the entry's atoms list is empty. An atom is "
        "a durable rule (convention/decision/deprecation/anti-pattern) that an AI "
        "coding agent should respect when modifying this codebase."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "extractions": {
                "type": "array",
                "description": (
                    "One entry per event in the input batch, in the same order. "
                    "event_index is 0-based and corresponds to the event's position "
                    "in the user message's batch."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "event_index": {
                            "type": "integer",
                            "description": "0-based index of the event in the user-message batch.",
                        },
                        "atoms": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "category": {
                                        "type": "string",
                                        "enum": ["convention", "decision", "deprecation", "anti-pattern"],
                                    },
                                    "summary": {
                                        "type": "string",
                                        "maxLength": 200,
                                        "description": (
                                            "One-line statement of the rule. Imperative voice "
                                            "when possible. e.g. 'Use Result<T> for domain errors.'"
                                        ),
                                    },
                                    "rationale": {
                                        "type": "string",
                                        "maxLength": 600,
                                        "description": "WHY the rule exists — cite the incident, PR, or principle.",
                                    },
                                    "scope": {
                                        "type": ["string", "null"],
                                        "description": "Glob applying the rule (e.g. 'routes/**') or null for repo-wide.",
                                    },
                                    "confidence": {
                                        "type": "number",
                                        "minimum": 0.0,
                                        "maximum": 1.0,
                                        "description": "How durable this rule is. 0.9+ explicit; 0.6-0.8 inferred; <0.6 guess.",
                                    },
                                },
                                "required": ["category", "summary", "confidence"],
                            },
                        },
                    },
                    "required": ["event_index", "atoms"],
                },
            },
        },
        "required": ["extractions"],
    },
}


# Stage 3 (Opus, with extended thinking): dedup + topic clustering + rule promotion.
STAGE3_TOOL = {
    "name": "structure_atoms",
    "description": (
        "Take a noisy set of raw atoms (from Stage 2 Sonnet, with many duplicates "
        "and overlapping rules) and produce: (1) a deduplicated canonical atom set "
        "where each canonical atom merges all raw atoms describing the same rule, "
        "(2) topic clusters that group related canonical atoms, (3) a rule-promotion "
        "flag for atoms that are universal team rules (high confidence, broad applicability)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "canonical_atoms": {
                "type": "array",
                "description": (
                    "Deduplicated atoms. When multiple raw atoms describe the same rule, "
                    "merge into one canonical atom. Preserve the strongest summary + rationale. "
                    "Combine source_refs from all merged raw atoms."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "raw_atom_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs of all raw atoms merged into this canonical atom.",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["convention", "decision", "deprecation", "anti-pattern"],
                        },
                        "summary": {
                            "type": "string",
                            "maxLength": 200,
                            "description": "Canonical one-line summary (the BEST phrasing across all merged raw atoms).",
                        },
                        "rationale": {
                            "type": "string",
                            "maxLength": 600,
                            "description": "Best combined rationale from the merged raw atoms.",
                        },
                        "scope": {"type": ["string", "null"]},
                        "confidence": {
                            "type": "number",
                            "minimum": 0.0,
                            "maximum": 1.0,
                            "description": "Reflects strength after dedup — usually higher than any individual raw atom because multiple sources reinforce it.",
                        },
                        "topic_id": {
                            "type": "string",
                            "description": "ID of the topic this atom belongs to (must match one of the `topics` IDs below).",
                        },
                        "is_rule": {
                            "type": "boolean",
                            "description": "True if this is a universal team rule that should always be surfaced to coding agents (high confidence ≥0.85, broad scope, explicit team decision).",
                        },
                    },
                    "required": ["raw_atom_ids", "category", "summary", "confidence", "topic_id", "is_rule"],
                },
            },
            "topics": {
                "type": "array",
                "description": (
                    "Topic clusters discovered. Group atoms by what they're ABOUT — error handling, "
                    "async patterns, database sessions, auth, testing, etc. Each canonical_atom "
                    "references one of these via topic_id."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "Short stable snake_case ID (e.g. 't_error_handling', 't_async_io', 't_db_sessions').",
                        },
                        "name": {
                            "type": "string",
                            "description": "Human-readable topic name (e.g. 'Error handling', 'Async I/O', 'Database sessions').",
                        },
                        "summary": {
                            "type": "string",
                            "maxLength": 200,
                            "description": "One-line summary of what conventions/decisions live in this topic.",
                        },
                    },
                    "required": ["id", "name", "summary"],
                },
            },
        },
        "required": ["canonical_atoms", "topics"],
    },
}

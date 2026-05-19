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
    summary: str = Field(..., max_length=200)
    rationale: str | None = Field(default=None, max_length=600)
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

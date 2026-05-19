"""Tier resolution for ContextLayer's request path.

Environment-driven, zero-config defaults:

    CONTEXTLAYER_TIER    = free | hybrid | premium     # default: hybrid
    ANTHROPIC_API_KEY    = <key>                       # presence enables LLM path

`free`     → deterministic only (Option B: keyless, fast, viral free tier)
`hybrid`   → deterministic first; escalate to LLM only on uncertainty (Option D, paid default)
`premium`  → LLM judge straight away (Option A, enterprise accuracy toggle)

BYOK is *additive*: any tier with a key set unlocks the LLM path; without
a key we degrade gracefully rather than failing.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

Tier = Literal["free", "hybrid", "premium"]


@dataclass(frozen=True)
class Routing:
    tier: Tier
    has_api_key: bool

    @property
    def can_call_llm(self) -> bool:
        return self.has_api_key and self.tier in ("hybrid", "premium")

    @property
    def llm_first(self) -> bool:
        """Premium tier: always start with the LLM judge."""
        return self.tier == "premium" and self.has_api_key

    @property
    def escalation_threshold(self) -> float:
        """Below this deterministic-confidence, hybrid tier escalates to LLM."""
        return {"free": 0.0, "hybrid": 0.6, "premium": 1.0}[self.tier]


def resolve() -> Routing:
    tier_raw = (os.environ.get("CONTEXTLAYER_TIER") or "hybrid").strip().lower()
    if tier_raw not in ("free", "hybrid", "premium"):
        tier_raw = "hybrid"
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return Routing(tier=tier_raw, has_api_key=has_key)  # type: ignore[arg-type]

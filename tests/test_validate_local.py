"""Deterministic validator unit tests — no LLM, no network."""
from __future__ import annotations

from contextlayer.validate_local import evaluate


_THREADING_RULE = {
    "id": "atom-async-first",
    "summary": "Don't use threading — this codebase is async-first.",
    "rationale": "All I/O must go through asyncio; threading deadlocks our event loop.",
    "scope": "src/api/**",
    "source_refs": ["pr:42:async-first"],
}

_SESSION_RULE = {
    "id": "atom-no-shared-session",
    "summary": "Never share a SQLAlchemy session across requests.",
    "rationale": "Shared sessions leak transactions; create a new one per request.",
    "scope": "src/db/**",
    "source_refs": ["pr:71:db-session"],
}

_RESULT_RULE = {
    "id": "atom-result-type",
    "summary": "Return Result<T> from fallible endpoints.",
    "rationale": "Errors must be typed.",
    "scope": "src/api/**",
    "source_refs": ["pr:33:result-type"],
}


def test_threading_violation_detected_without_llm():
    change = "I'll add src/api/billing.py that spawns a threading.Thread to fetch the history."
    v = evaluate(change, [_THREADING_RULE, _RESULT_RULE])
    assert not v.passes
    ids = [x["rule_id"] for x in v.violations]
    assert "atom-async-first" in ids
    assert v.confidence >= 0.55


def test_scope_skips_irrelevant_rule():
    # Change is in src/cli/ — async-first rule scope is src/api/**, so should be skipped.
    change = "Add src/cli/dump.py that calls threading.Thread to parallelize a CLI dump."
    v = evaluate(change, [_THREADING_RULE])
    # Rule scope doesn't apply → no violation flagged, rule skipped.
    assert v.passes
    assert "atom-async-first" in v.rules_skipped_out_of_scope


def test_clean_change_passes_with_moderate_confidence():
    change = "Refactor src/api/users.py to return Result<User> from get_user — fully async."
    v = evaluate(change, [_THREADING_RULE, _RESULT_RULE])
    assert v.passes
    assert v.violations == []
    # Multiple applicable rules → confidence should be at least mid.
    assert v.confidence >= 0.55


def test_forbidden_phrase_detected_from_rule_text():
    """Forbidden phrases are mined from the rule itself ('never share a session')."""
    rule = {
        "id": "atom-no-eval",
        "summary": "Never use eval() in user-input paths.",
        "rationale": "Arbitrary code execution risk.",
        "scope": None,
        "source_refs": [],
    }
    change = "Quick fix: just eval(input_str) and we're done."
    v = evaluate(change, [rule])
    assert not v.passes
    assert v.violations[0]["rule_id"] == "atom-no-eval"


def test_unrelated_change_no_false_positive():
    change = "Update README typo in the installation section."
    v = evaluate(change, [_THREADING_RULE, _SESSION_RULE])
    assert v.passes


def test_empty_rules_returns_pass_with_low_confidence():
    v = evaluate("anything", [])
    assert v.passes
    assert v.confidence <= 0.4

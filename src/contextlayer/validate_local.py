"""Deterministic, keyless validator.

The previous no-key fallback in `context_validate` just handed the rules
back to the caller and asked them to self-judge. That's fine for a
hand-off, useless as a product.

This module produces an actual verdict using only local signals:

  1. Scope detector — if a rule's `scope` is `src/api/**` and the change
     never mentions that path, mark the rule non-applicable (skip).
  2. Forbidden-phrase detector — parses "don't / never / avoid /
     prohibited / not allowed" clauses out of the rule's summary +
     rationale and checks for the offending phrase in the change.
  3. Anti-pattern map — small curated set of patterns rules commonly
     forbid (threading, time.sleep, raw SQL, print debugging, eval,
     etc.) — only triggered when the rule itself mentions that topic.
  4. Confidence — derived from how many signals fired and how clean
     the matches are. Hybrid tier escalates when confidence < 0.6.

Output is a drop-in for the LLM judge's verdict.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ---- 1. Curated anti-pattern map ---------------------------------------------
# Keyed by topic tokens that, when present in a rule, activate the corresponding
# code-side regex. Conservative on purpose — false positives are worse than
# misses since the LLM tier can catch what we don't.
_ANTI_PATTERNS: list[tuple[set[str], re.Pattern[str], str]] = [
    (
        {"thread", "threading", "concurrency", "async", "async-first"},
        re.compile(r"\b(threading\.|Thread\(|threading\s*\.)|\bfrom\s+threading\b"),
        "uses the `threading` module",
    ),
    (
        {"sleep", "block", "blocking"},
        re.compile(r"\btime\.sleep\("),
        "calls `time.sleep` (blocking)",
    ),
    (
        {"print", "debug", "logging"},
        re.compile(r"^\s*print\(", re.MULTILINE),
        "uses `print(` for debugging",
    ),
    (
        {"sql", "injection", "parameterize", "parameterised", "parameterized"},
        re.compile(r"""(?:execute|executemany)\(\s*f["']|%\s*\(.*\)\s*s|\+\s*['"]\s*SELECT""", re.IGNORECASE),
        "appears to build raw SQL via f-string / string concat",
    ),
    (
        {"eval", "exec", "unsafe"},
        re.compile(r"\b(eval|exec)\s*\("),
        "uses `eval(` or `exec(`",
    ),
    (
        {"session", "sqlalchemy", "transaction"},
        re.compile(r"\bglobal\s+session\b|shared_session", re.IGNORECASE),
        "appears to share a SQLAlchemy session",
    ),
]

# ---- 2. Negation / forbidding phrasing in rule text --------------------------
_NEGATION_RE = re.compile(
    r"\b(?:do\s+not|don'?t|never|avoid|prohibited|not\s+allowed|must\s+not|"
    r"should\s+not|shouldn'?t|forbidden|disallowed|no\s+raw|no\s+unsafe)\b"
    r"\s+([a-z][\w\s\-\.]{2,60}?)(?=[\.,;:!?\n]|$)",
    re.IGNORECASE,
)

# ---- 3. Scope path matcher ---------------------------------------------------
_PATH_TOKEN_RE = re.compile(r"[a-zA-Z0-9_\-/\.]+")
_WORD_RE = re.compile(r"[a-z][a-z0-9_]+")


def _word_tokens(text: str) -> set[str]:
    """Lowercase alphanumeric tokens — used for topic-set matching so that
    'eval()' and 'eval' compare equal."""
    return set(_WORD_RE.findall((text or "").lower()))


@dataclass
class Signal:
    rule_id: str
    why: str
    severity: str = "medium"


@dataclass
class LocalVerdict:
    passes: bool
    violations: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.5
    rules_considered: int = 0
    rules_skipped_out_of_scope: list[str] = field(default_factory=list)


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    # Tiny glob-ish translator: `**` → `.*`, `*` → `[^/]*`, anchor unanchored.
    p = re.escape(pattern)
    p = p.replace(r"\*\*", r".*").replace(r"\*", r"[^/]*")
    return re.compile(p)


def _scope_applies(rule_scope: str | None, change: str) -> bool:
    """True if the change text plausibly falls inside the rule's scope.

    If the rule has no scope → applies (conservative). If the scope is a
    glob, we look for matching path-like tokens in the change.
    """
    if not rule_scope:
        return True
    scope_re = _glob_to_regex(rule_scope)
    for tok in _PATH_TOKEN_RE.findall(change):
        if "/" in tok or "." in tok:
            if scope_re.search(tok):
                return True
    # No path-like tokens at all → can't disprove applicability; assume yes.
    if not any(("/" in t or "." in t) for t in _PATH_TOKEN_RE.findall(change)):
        return True
    return False


def _forbidden_phrases(rule_text: str) -> list[str]:
    """Pull noun phrases that follow negation cues in the rule text."""
    out: list[str] = []
    for m in _NEGATION_RE.finditer(rule_text or ""):
        phrase = m.group(1).strip().lower()
        # Truncate to first 4 words — keeps the check tight, avoids whole-sentence false positives.
        words = phrase.split()
        if 1 <= len(words) <= 6:
            out.append(" ".join(words[:4]))
    return out


_PHRASE_STOPHEADS = frozenset({"use", "using", "make", "do", "have", "be", "a", "an", "the", "any", "all"})


def _phrase_hit(phrase: str, change_lower: str) -> bool:
    """True if the phrase (or its head noun) appears in the change.

    For multi-word phrases like "use eval" we try the full string first,
    then fall back to the last meaningful word ('eval') so that "eval(x)"
    in the change still matches the rule's "never use eval".
    """
    candidates: list[str] = []
    cleaned = phrase.strip()
    if cleaned:
        candidates.append(cleaned)
    words = [w for w in cleaned.split() if w]
    if len(words) > 1:
        head = words[-1]
        if head not in _PHRASE_STOPHEADS and len(head) >= 3:
            candidates.append(head)
    for cand in candidates:
        base = cand
        if base.endswith("ing") and len(base) > 4:
            base = base[:-3]
        elif base.endswith("s") and len(base) > 3:
            base = base[:-1]
        if len(base) < 3:
            continue
        if re.search(rf"\b{re.escape(base)}", change_lower):
            return True
    return False


def evaluate(proposed_change: str, rules: list[dict[str, Any]]) -> LocalVerdict:
    """Run all deterministic detectors over the candidate rules.

    `rules` is the list shape produced by `cosine_search` / the MCP layer
    (dicts with id, summary, rationale, scope, source_refs, ...).
    """
    change = proposed_change or ""
    change_lower = change.lower()
    violations: list[dict[str, Any]] = []
    skipped: list[str] = []
    total_signals = 0

    for rule in rules:
        rid = rule.get("id", "?")
        summary = rule.get("summary") or ""
        rationale = rule.get("rationale") or ""
        scope = rule.get("scope")
        rule_text = f"{summary}\n{rationale}".lower()
        rule_token_set = _word_tokens(rule_text)

        # Skip rules whose scope clearly doesn't apply.
        if not _scope_applies(scope, change):
            skipped.append(rid)
            continue

        triggered: list[str] = []

        # (A) Forbidden phrases mined from the rule itself.
        for phrase in _forbidden_phrases(f"{summary} {rationale}"):
            if _phrase_hit(phrase, change_lower):
                triggered.append(f"contains forbidden phrase '{phrase}'")
                break  # one is enough; avoid spam

        # (B) Curated anti-pattern map, gated by topic overlap with the rule.
        for topics, regex, why in _ANTI_PATTERNS:
            if not (topics & rule_token_set):
                continue
            if regex.search(change):
                triggered.append(why)
                break

        if triggered:
            total_signals += len(triggered)
            violations.append({
                "rule_id": rid,
                "rule_summary": summary,
                "why_violated": "; ".join(triggered),
                "severity": "high" if len(triggered) >= 2 else "medium",
                "source_refs": rule.get("source_refs", []),
                "scope": scope,
            })

    n_rules = len(rules)
    # Confidence model:
    #   - If we found violations with multiple signals each → high confidence.
    #   - If we found 0 violations across many rules → mid confidence (could be a true clean change).
    #   - If we evaluated very few applicable rules → low confidence.
    applicable = n_rules - len(skipped)
    if applicable == 0:
        confidence = 0.3
    elif violations:
        confidence = min(0.95, 0.55 + 0.1 * total_signals)
    else:
        confidence = 0.55 + min(0.3, applicable * 0.05)

    return LocalVerdict(
        passes=not violations,
        violations=violations,
        confidence=round(confidence, 3),
        rules_considered=n_rules,
        rules_skipped_out_of_scope=skipped,
    )

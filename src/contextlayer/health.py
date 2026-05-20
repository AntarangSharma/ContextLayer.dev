"""Convention Health Score — compute a 0-100 letter-graded health snapshot for an indexed repo.

Per spec §5.7.5. The score is the canonical "is my convention index actually
useful?" signal: enough atoms, enough rules, enough topic breadth, citations,
freshness, and no contradictory rules.

The score is fully deterministic — no LLM calls — so it's safe to gate CI on.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Weights sum to 100 — see spec §5.7.5 for the rationale on each dimension.
_WEIGHT_ATOMS = 20
_WEIGHT_RULES = 20
_WEIGHT_TOPICS = 15
_WEIGHT_CITATIONS = 15
_WEIGHT_FRESHNESS = 15
_WEIGHT_CONFLICTS = 15

_POSITIVE_OBLIGATION = re.compile(r"\b(must|required|always|shall)\b", re.IGNORECASE)
_NEGATIVE_OBLIGATION = re.compile(
    r"\b(do not|don't|never|avoid|deprecated|stop using|forbidden|disallow(?:ed)?)\b",
    re.IGNORECASE,
)

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_/.]*[A-Za-z0-9]")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "to", "of", "in",
    "on", "for", "and", "or", "but", "not", "no", "do", "don", "use", "using",
    "with", "by", "from", "this", "that", "it", "as", "at", "we", "you",
    "must", "should", "never", "always", "avoid", "deprecated", "rule",
    "scope", "all", "any", "ever", "have", "has", "had", "via", "per",
    "instead", "can",
}


@dataclass
class HealthReport:
    """Everything a caller needs to render or serialize a health snapshot."""
    score: int
    grade: str
    n_atoms: int
    n_rules: int
    n_topics: int
    n_citations: int
    stale_rules: int
    conflicts: list[tuple[str, str, str]]
    breakdown: dict[str, int] = field(default_factory=dict)


def letter_grade(score: int) -> str:
    """Spec-defined boundaries."""
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 50: return "D"
    return "F"


def _score_count(n: int, tiers: list[tuple[int, int]]) -> int:
    """Tiered step function. tiers sorted ascending by threshold."""
    out = 0
    for threshold, pts in tiers:
        if n >= threshold:
            out = pts
    return out


def _score_pct(pct: float, tiers: list[tuple[float, int]]) -> int:
    """Same as _score_count but for [0.0, 1.0] fractions."""
    out = 0
    for threshold, pts in tiers:
        if pct >= threshold:
            out = pts
    return out


def _parse_dt(raw: str | None) -> datetime | None:
    """Best-effort parse of stored ISO 8601 / float-epoch timestamps."""
    if not raw:
        return None
    try:
        if "T" in raw or "-" in raw:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return datetime.fromtimestamp(float(raw), tz=timezone.utc)
    except (ValueError, TypeError):
        return None


def _keywords(text: str) -> set[str]:
    """Extract *concrete* identifier-like tokens from a rule summary.

    Only returns tokens that look like real code identifiers — compound
    (snake_case / dotted / slashed / hyphenated), camelCase, or long
    lowercase words (≥7 chars). This deliberately excludes short English
    words like 'route', 'depends', 'use' that otherwise produce noisy
    cross-rule "conflicts".
    """
    if not text:
        return set()
    out: set[str] = set()
    for m in _IDENT_RE.finditer(text):
        tok = m.group(0)
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        if len(tok) < 3:
            continue
        is_compound = any(c in tok for c in "_/.-")
        is_camel = any(c.isupper() for c in tok[1:])
        is_long = len(tok) >= 7
        if not (is_compound or is_camel or is_long):
            continue
        out.add(low)
    return out


def _scopes_overlap(a: str | None, b: str | None) -> bool:
    """Conservative overlap: None scope = global (matches everything).

    Two concrete scopes overlap iff they share their leading path segment up to
    the first glob character.
    """
    if a is None or b is None:
        return True

    def head(scope: str) -> str:
        scope = scope.strip()
        for i, ch in enumerate(scope):
            if ch in "*?[":
                return scope[:i].rstrip("/")
        return scope.rsplit("/", 1)[0] if "/" in scope else scope

    ha, hb = head(a), head(b)
    if not ha or not hb:
        return True
    return ha.startswith(hb) or hb.startswith(ha)


def detect_conflicts(rules: list[dict]) -> list[tuple[str, str, str]]:
    """Pairwise rule conflict detection.

    A pair (A, B) conflicts when:
      - their scopes overlap, AND
      - one expresses a positive obligation (MUST/REQUIRED) and the other a
        negative one (NEVER/DO NOT/AVOID), AND
      - they share at least one significant subject token.
    """
    conflicts: list[tuple[str, str, str]] = []
    enriched = []
    for r in rules:
        s = r["summary"] or ""
        has_pos = bool(_POSITIVE_OBLIGATION.search(s))
        has_neg = bool(_NEGATIVE_OBLIGATION.search(s))
        # A rule containing BOTH polarities (e.g. "Do not use X; must use Y") is
        # internally a single coherent decision and shouldn't be flagged against
        # other rules — collapse it to neither polarity.
        if has_pos and has_neg:
            polarity = None
        elif has_pos:
            polarity = "pos"
        elif has_neg:
            polarity = "neg"
        else:
            polarity = None
        enriched.append({
            "id": r["id"],
            "scope": r.get("scope"),
            "summary": s,
            "kw": _keywords(s),
            "polarity": polarity,
        })

    for i, a in enumerate(enriched):
        for b in enriched[i + 1:]:
            if a["polarity"] is None or b["polarity"] is None:
                continue
            if a["polarity"] == b["polarity"]:
                continue
            if not _scopes_overlap(a["scope"], b["scope"]):
                continue
            shared = a["kw"] & b["kw"]
            if not shared:
                continue
            sample = sorted(shared)[0]
            conflicts.append((
                a["id"], b["id"],
                f"both rules touch '{sample}' on overlapping scope with opposing polarity",
            ))
    return conflicts


def compute_health(db_path: Path | str) -> HealthReport:
    """Compute the health report from an indexed SQLite DB. Pure read."""
    db_path = Path(db_path)
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, summary, scope, source_refs, confidence, is_rule, created_at "
            "FROM atoms"
        ).fetchall()
        n_topics = conn.execute("SELECT count(*) FROM topics").fetchone()[0]
    finally:
        conn.close()

    atoms: list[dict] = []
    for r in rows:
        try:
            refs = json.loads(r[3] or "[]")
        except (TypeError, ValueError):
            refs = []
        atoms.append({
            "id": r[0],
            "summary": r[1],
            "scope": r[2],
            "source_refs": refs,
            "confidence": r[4],
            "is_rule": bool(r[5]),
            "created_at": r[6],
        })

    n_atoms = len(atoms)
    rules = [a for a in atoms if a["is_rule"]]
    n_rules = len(rules)
    n_citations = sum(len(a["source_refs"]) for a in atoms)

    if n_atoms == 0:
        coverage = 0.0
        freshness = 0.0
        stale_rules = 0
    else:
        with_refs = sum(1 for a in atoms if a["source_refs"])
        coverage = with_refs / n_atoms

        now = datetime.now(timezone.utc)
        fresh_count = 0
        stale_rules = 0
        for a in atoms:
            dt = _parse_dt(a["created_at"])
            if dt is None:
                continue
            age_days = (now - dt).days
            if age_days <= 90:
                fresh_count += 1
            elif a["is_rule"]:
                stale_rules += 1
        freshness = fresh_count / n_atoms

    conflicts = detect_conflicts(rules)

    s_atoms = _score_count(n_atoms, [(0, 0), (5, 10), (10, 15), (15, 20)])
    s_rules = _score_count(n_rules, [(0, 0), (3, 10), (5, 15), (8, 20)])
    s_topics = _score_count(n_topics, [(0, 0), (3, 8), (5, 12), (7, 15)])
    s_citations = _score_pct(coverage, [(0.0, 0), (0.5, 8), (0.8, 12), (1.0, 15)])
    s_freshness = _score_pct(freshness, [(0.0, 0), (0.5, 8), (0.8, 12), (1.0, 15)])
    s_conflicts = max(0, _WEIGHT_CONFLICTS - 3 * len(conflicts))

    total = s_atoms + s_rules + s_topics + s_citations + s_freshness + s_conflicts
    score = max(0, min(100, total))

    return HealthReport(
        score=score,
        grade=letter_grade(score),
        n_atoms=n_atoms,
        n_rules=n_rules,
        n_topics=n_topics,
        n_citations=n_citations,
        stale_rules=stale_rules,
        conflicts=conflicts,
        breakdown={
            "atoms": s_atoms,
            "rules": s_rules,
            "topics": s_topics,
            "citations": s_citations,
            "freshness": s_freshness,
            "conflict_free": s_conflicts,
        },
    )


def render_panel(report: HealthReport) -> str:
    """Render the health report as a rich-formatted box."""
    from io import StringIO
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text

    body = Text()
    body.append(f"Convention Health: {report.grade} ({report.score}/100)\n", style="bold")
    body.append("\n")

    def line(symbol: str, msg: str, style: str) -> None:
        body.append(f"  {symbol} ", style=style)
        body.append(msg + "\n")

    line("✓", f"{report.n_atoms} atoms extracted", "green")
    line("✓", f"{report.n_rules} rules promoted", "green")
    line("✓", f"{report.n_topics} topics discovered", "green")
    line("✓", f"{report.n_citations} PR/commit citations", "green")
    if report.stale_rules:
        line("⚠", f"{report.stale_rules} stale rules (>90 days)", "yellow")
    if report.conflicts:
        n = len(report.conflicts)
        word = "conflict" if n == 1 else "conflicts"
        line("✗", f"{n} potential {word} detected", "red")
    if not report.stale_rules and not report.conflicts:
        line("✓", "No stale rules, no conflicts", "green")

    body.append("\n")
    body.append("  Run: contextlayer drift --last 5\n", style="dim")
    body.append("  to check recent compliance.", style="dim")

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=60)
    console.print(Panel(body, padding=(0, 1), expand=False, border_style="cyan"))
    return buf.getvalue()


def report_to_json(report: HealthReport) -> dict:
    """JSON-serializable dict for `--json` output."""
    return {
        "score": report.score,
        "grade": report.grade,
        "atoms": report.n_atoms,
        "rules": report.n_rules,
        "topics": report.n_topics,
        "citations": report.n_citations,
        "stale_rules": report.stale_rules,
        "conflicts": [
            {"atom_a": a, "atom_b": b, "reason": reason}
            for a, b, reason in report.conflicts
        ],
        "breakdown": report.breakdown,
    }

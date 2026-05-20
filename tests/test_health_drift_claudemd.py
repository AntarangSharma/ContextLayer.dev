"""Unit tests for the three new v1.1 features: health, drift, claude-md.

These run against an in-memory-ish temp SQLite — no API calls, no
demo DB dependency.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from contextlayer.claude_md import _format_citation, render
from contextlayer.drift import _extract_triggers, check_drift
from contextlayer.health import (
    compute_health,
    detect_conflicts,
    letter_grade,
    _scopes_overlap,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_db(tmp_path: Path, atoms: list[dict], topics: list[dict] | None = None) -> Path:
    """Build a minimal SQLite DB matching the production schema for testing."""
    db = tmp_path / "index.db"
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE atoms (
            id TEXT PRIMARY KEY, category TEXT NOT NULL, summary TEXT NOT NULL,
            rationale TEXT, scope TEXT, source_refs TEXT NOT NULL,
            confidence REAL NOT NULL, is_rule INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE TABLE topics (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, summary TEXT,
            atom_ids TEXT NOT NULL
        );
    """)
    now = datetime.now(timezone.utc).isoformat()
    for a in atoms:
        conn.execute(
            "INSERT INTO atoms VALUES (?,?,?,?,?,?,?,?,?)",
            (
                a["id"], a.get("category", "rule"), a["summary"],
                a.get("rationale"), a.get("scope"),
                json.dumps(a.get("source_refs", [])),
                a.get("confidence", 0.9),
                int(a.get("is_rule", False)),
                a.get("created_at", now),
            ),
        )
    for t in topics or []:
        conn.execute(
            "INSERT INTO topics VALUES (?,?,?,?)",
            (t["id"], t["name"], t.get("summary"), json.dumps(t["atom_ids"])),
        )
    conn.commit()
    conn.close()
    return db


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

def test_letter_grade_boundaries():
    assert letter_grade(100) == "A+"
    assert letter_grade(95) == "A+"
    assert letter_grade(94) == "A"
    assert letter_grade(80) == "B+"
    assert letter_grade(49) == "F"


def test_scopes_overlap_cases():
    assert _scopes_overlap(None, "routes/**") is True
    assert _scopes_overlap("routes/**", "routes/api/x.py") is True
    assert _scopes_overlap("routes/**", "models/**") is False
    assert _scopes_overlap("src/middleware/auth.py", "src/middleware/**") is True


def test_empty_db_scores_low(tmp_path):
    # Per spec: conflict_free starts at 15 (no conflicts possible with 0 atoms),
    # all other dimensions score 0. Total = 15, grade F.
    db = _make_db(tmp_path, atoms=[])
    report = compute_health(db)
    assert report.score == 15
    assert report.grade == "F"
    assert report.n_atoms == 0
    assert report.breakdown["atoms"] == 0
    assert report.breakdown["rules"] == 0


def test_healthy_db_scores_high(tmp_path):
    atoms = [
        {"id": f"a{i}", "summary": f"Rule {i} must do thing", "is_rule": i < 8,
         "source_refs": [f"pr:{i}:description"]}
        for i in range(15)
    ]
    topics = [
        {"id": f"t{i}", "name": f"Topic {i}", "atom_ids": [f"a{i}"]}
        for i in range(7)
    ]
    db = _make_db(tmp_path, atoms, topics)
    report = compute_health(db)
    assert report.score >= 95
    assert report.grade.startswith("A")
    assert report.n_atoms == 15
    assert report.n_rules == 8
    assert report.n_topics == 7
    assert report.conflicts == []


def test_conflict_detection_pos_vs_neg():
    rules = [
        {"id": "a1", "summary": "Handlers MUST use Depends(get_session).", "scope": "routes/**"},
        {"id": "a2", "summary": "Do not use Depends(get_session).", "scope": "routes/api/**"},
    ]
    conflicts = detect_conflicts(rules)
    assert len(conflicts) == 1
    assert {conflicts[0][0], conflicts[0][1]} == {"a1", "a2"}


def test_conflict_detection_skips_mixed_polarity():
    # A single rule containing both "do not" and "must" is internally coherent.
    rules = [
        {"id": "a1", "summary": "Do not use X; you MUST use Y instead.", "scope": None},
        {"id": "a2", "summary": "Do not use X.", "scope": None},
    ]
    # a1 is mixed-polarity (collapsed to None); a2 is purely negative.
    # No opposing polarity pair → no conflict.
    assert detect_conflicts(rules) == []


def test_stale_rules_counted(tmp_path):
    old = (datetime.now(timezone.utc) - timedelta(days=180)).isoformat()
    new = datetime.now(timezone.utc).isoformat()
    atoms = [
        {"id": "a1", "summary": "do X", "is_rule": True, "created_at": old,
         "source_refs": ["pr:1:description"]},
        {"id": "a2", "summary": "do Y", "is_rule": False, "created_at": new,
         "source_refs": ["pr:2:description"]},
    ]
    report = compute_health(_make_db(tmp_path, atoms))
    assert report.stale_rules == 1


# ---------------------------------------------------------------------------
# Drift
# ---------------------------------------------------------------------------

def test_extract_triggers_strips_replacement():
    s = "Do not use utils/db_helper; use Depends(get_session) instead."
    triggers = _extract_triggers(s)
    assert "utils/db_helper" in triggers
    # The replacement should be excluded.
    assert "get_session" not in triggers
    assert "depends" not in triggers


def test_extract_triggers_skips_positive_rules():
    assert _extract_triggers("Handlers MUST use Result<T>.") == []


def test_extract_triggers_skips_bare_english_words():
    # 'session' alone (no separator) shouldn't be a trigger.
    assert "session" not in _extract_triggers("Never share session across requests.")


def test_drift_flags_violating_commit(tmp_path):
    # Build a tiny git repo with one commit that mentions the forbidden token.
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.py").write_text("from utils.db_helper import query\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Quick fix: use utils/db_helper for migration"],
        cwd=repo, check=True,
    )

    atoms = [{
        "id": "a1",
        "summary": "Do not use utils/db_helper; use Depends(get_session) instead.",
        "is_rule": True,
        "source_refs": ["pr:8:description"],
    }]
    db = _make_db(tmp_path, atoms)
    violations, n_commits = check_drift(db, repo, last=5)
    assert n_commits == 1
    assert len(violations) == 1
    assert violations[0].rule_id == "a1"
    assert "utils/db_helper" in violations[0].matched_tokens
    assert violations[0].rule_source == "PR #8"


def test_drift_skips_rule_source_commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "a.py").write_text("from utils.db_helper import query\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "Deprecate utils/db_helper"],
        cwd=repo, check=True,
    )
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()

    # Rule was extracted from this very commit → must not fire on it.
    atoms = [{
        "id": "a1",
        "summary": "Do not use utils/db_helper; use Depends(get_session) instead.",
        "is_rule": True,
        "source_refs": [f"commit:{sha}", "pr:8:description"],
    }]
    db = _make_db(tmp_path, atoms)
    violations, _ = check_drift(db, repo, last=5)
    assert violations == []


# ---------------------------------------------------------------------------
# CLAUDE.md
# ---------------------------------------------------------------------------

def test_format_citation_dedupes_prs():
    refs = ["pr:3:description", "pr:3:review:3", "commit:dce6492abc123"]
    assert _format_citation(refs) == "PR #3, commit dce6492"


def test_format_citation_handles_notes():
    refs = ["note:2026-05-19T01:20:34.612138+00:00"]
    assert _format_citation(refs) == "note 2026-05-19"


def test_render_groups_by_topic(tmp_path):
    atoms = [
        {"id": "a1", "summary": "Use Result<T>", "is_rule": True,
         "source_refs": ["pr:3:description"], "confidence": 0.95},
        {"id": "a2", "summary": "HTTP wrapper converts Result.err to 4xx", "is_rule": False,
         "source_refs": ["pr:6:description"], "confidence": 0.8},
        {"id": "a3", "summary": "NEVER share sessions", "is_rule": True,
         "source_refs": ["pr:14:description"], "confidence": 0.96, "scope": "routes/**"},
    ]
    topics = [
        {"id": "t1", "name": "Error handling", "atom_ids": ["a1", "a2"]},
        {"id": "t2", "name": "Database sessions", "atom_ids": ["a3"]},
    ]
    db = _make_db(tmp_path, atoms, topics)
    md = render(db, "test-repo")

    assert "# CLAUDE.md — Auto-generated conventions for test-repo" in md
    assert "## Error handling" in md
    assert "## Database sessions" in md
    # Rules section appears before Conventions within Error handling.
    eh_section = md.split("## Error handling", 1)[1].split("## Database sessions")[0]
    assert eh_section.index("### Rules") < eh_section.index("### Conventions")
    # Scope rendered for the scoped rule.
    assert "[Scope: routes/**]" in md
    # Citations inlined.
    assert "(Source: PR #3)" in md
    assert "(Source: PR #14)" in md
    # Footer present.
    assert "auto-generated by [ContextLayer.dev]" in md


def test_render_emits_orphan_atoms_under_other(tmp_path):
    atoms = [
        {"id": "a1", "summary": "Orphan note", "is_rule": False,
         "source_refs": ["note:2026-05-19T00:00:00+00:00"]},
    ]
    db = _make_db(tmp_path, atoms, topics=[])
    md = render(db, "r")
    assert "## Other" in md
    assert "Orphan note" in md

"""GitHub PR adapter — splits each commit's body into a PR description event
and zero-or-more PR review-comment events.

Two paths, selected automatically:

  - Synthetic shim: when the repo has no `origin` remote pointing at github.com,
    or when each commit body contains the `---REVIEW COMMENTS---` marker
    (the format produced by demo-data/build_acme.py). Each PR description ==
    the commit body up to that marker; each line `@<reviewer>: <text>` after
    the marker is one review comment.

  - Real path: `gh pr list --state merged --json ...` + `gh pr view <n> --json`.
    Implemented later (deferred behind --use-gh; the synthetic shim handles the
    primary demo path per Appendix A #16 of the design spec).

Both paths yield the same RawEvent shape so downstream stages don't care.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

from contextlayer.ingest import RawEvent

_REVIEW_MARKER = "---REVIEW COMMENTS---"


def _git_log_full_messages(repo_path: Path) -> list[tuple[str, str, str]]:
    """Return [(sha, iso_date, full_message), ...] in chronological order."""
    sep = "\x1e"  # record separator
    fld = "\x1f"  # field separator
    result = subprocess.run(
        ["git", "log", "--reverse", f"--format=%H{fld}%aI{fld}%B{sep}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    out: list[tuple[str, str, str]] = []
    for rec in result.stdout.split(sep):
        rec = rec.strip("\n")
        if not rec:
            continue
        parts = rec.split(fld, 2)
        if len(parts) != 3:
            continue
        sha, iso_date, body = parts
        out.append((sha, iso_date, body))
    return out


def _is_real_github_repo(repo_path: Path) -> bool:
    """True if `origin` points at github.com (and is fetchable)."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False
    return "github.com" in result.stdout


def _split_pr_body(commit_message: str) -> tuple[str, list[tuple[str, str]]]:
    """Split a commit message into (pr_description_text, [(reviewer, comment), ...]).

    Description text = subject line + blank line + body up to the marker.
    """
    if _REVIEW_MARKER not in commit_message:
        # No review block; treat the entire commit message as the description.
        return commit_message.rstrip(), []

    head, _, tail = commit_message.partition(_REVIEW_MARKER)
    description = head.rstrip()
    reviews: list[tuple[str, str]] = []
    for line in tail.strip("\n").splitlines():
        line = line.rstrip()
        if not line or not line.startswith("@"):
            continue
        # Format: "@reviewer: comment"
        try:
            handle_part, comment = line.split(":", 1)
            reviewer = handle_part[1:].strip()
            reviews.append((reviewer, comment.strip()))
        except ValueError:
            continue
    return description, reviews


def _synthetic_ingest(repo_path: Path) -> list[RawEvent]:
    """Synthetic-shim path. Each commit's body is parsed for PR description + reviews."""
    events: list[RawEvent] = []
    for pr_number, (sha, iso_date, body) in enumerate(_git_log_full_messages(repo_path), start=1):
        description, reviews = _split_pr_body(body)
        if not description:
            continue
        events.append(
            RawEvent(
                source_type="pr_description",
                source_id=f"pr:{pr_number}:description",
                timestamp=iso_date,
                text=description,
                metadata={
                    "pr_number": pr_number,
                    "commit_sha": sha,
                    "shim": "synthetic_from_commit_body",
                },
            )
        )
        for i, (reviewer, comment) in enumerate(reviews):
            events.append(
                RawEvent(
                    source_type="pr_review_comment",
                    source_id=f"pr:{pr_number}:review:{i}",
                    timestamp=iso_date,
                    text=comment,
                    metadata={
                        "pr_number": pr_number,
                        "commit_sha": sha,
                        "reviewer": reviewer,
                        "shim": "synthetic_from_commit_body",
                    },
                )
            )
    return events


def _real_ingest(repo_path: Path) -> list[RawEvent]:
    """Real-repo path using gh CLI. Implemented in Phase 2 polish (T+24+).

    For T+4 → T+8, the primary demo path is the synthetic shim. Real-repo
    ingestion stays a stub so judges can swap in FastAPI later via the
    Phase 3 stretch (T+34 → T+36).
    """
    raise NotImplementedError(
        "gh_prs._real_ingest: not implemented in Phase 1. The synthetic shim "
        "handles the primary demo path. Real-repo support lands in the Phase 3 "
        "FastAPI stretch (T+34) — see tasks/todo.md."
    )


def ingest(repo_path: str | Path) -> list[RawEvent]:
    """Auto-select synthetic shim vs real gh-CLI path.

    Selection rule: if every commit body contains `---REVIEW COMMENTS---`, treat as
    synthetic. Otherwise treat as real GitHub repo (which currently raises
    NotImplementedError; the stretch lands at T+34).
    """
    repo_path = Path(repo_path).resolve()
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")

    messages = _git_log_full_messages(repo_path)
    if not messages:
        return []
    all_have_marker = all(_REVIEW_MARKER in body for _, _, body in messages)
    if all_have_marker:
        return _synthetic_ingest(repo_path)
    return _real_ingest(repo_path)

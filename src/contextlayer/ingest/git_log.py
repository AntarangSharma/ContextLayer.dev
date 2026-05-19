"""git log adapter — one RawEvent per commit on the default branch.

Phase 1 simplification: we don't capture files-changed metadata. Stage 2 Sonnet
extracts atoms from commit message text; files are useful for atom `scope`
(spec §5.3) but that's a Phase 2 polish concern.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from contextlayer.ingest import RawEvent

_FIELD_SEP = "\x1f"  # ASCII Unit Separator
_RECORD_SEP = "\x1e"  # ASCII Record Separator


def _run_git_log(repo_path: Path) -> str:
    """One git log call returning all commits in chronological order.

    Format: %H\\x1f%aI\\x1f%an\\x1f%ae\\x1f%s\\x1f%B\\x1e

    %B is the full raw body (subject + blank + body). We separate fields with
    \\x1f and records with \\x1e so multi-line commit bodies parse correctly.
    """
    fmt = _FIELD_SEP.join(["%H", "%aI", "%an", "%ae", "%s", "%B"]) + _RECORD_SEP
    result = subprocess.run(
        ["git", "log", "--reverse", f"--format={fmt}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def ingest(repo_path: str | Path) -> list[RawEvent]:
    """Parse `git log` into RawEvent records (one per commit).

    `text` = the full raw body (`%B`) — subject + blank + body. The subject is
    duplicated inside `%B`, which is fine for Haiku/Sonnet (more signal beats
    more cleanup code).
    """
    repo_path = Path(repo_path).resolve()
    if not (repo_path / ".git").exists():
        raise ValueError(f"Not a git repository: {repo_path}")

    raw = _run_git_log(repo_path)
    events: list[RawEvent] = []

    for record in raw.split(_RECORD_SEP):
        record = record.strip("\n")
        if not record:
            continue
        parts = record.split(_FIELD_SEP, 5)
        if len(parts) < 6:
            continue
        sha, iso_date, author_name, author_email, subject, body = parts
        events.append(
            RawEvent(
                source_type="git_commit",
                source_id=f"commit:{sha}",
                timestamp=iso_date,
                text=body.rstrip("\n"),
                metadata={
                    "sha": sha,
                    "subject": subject,
                    "author_name": author_name,
                    "author_email": author_email,
                },
            )
        )
    return events

"""GitHub PR adapter — implemented at T+4 (Phase 1 ingestion).

For real repos: uses `gh pr list --state merged --json` + `gh pr view <n>`.
For the synthetic acme-billing-api repo: shim that reads commit body + git notes.
"""
from __future__ import annotations

from contextlayer.ingest.git_log import RawEvent


def ingest(repo_path: str) -> list[RawEvent]:
    """Stub. Will use gh CLI for real repos, commit-body shim for synthetic."""
    raise NotImplementedError("ingest.gh_prs.ingest — implemented at T+4")

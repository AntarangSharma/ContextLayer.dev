"""Ingestion: convert a repo's git + PR history into RawEvent records.

Two adapters:
    git_log   — one RawEvent per commit (source_type='git_commit')
    gh_prs    — PR descriptions + review comments (synthetic-shim or gh CLI)

`ingest_repo(path)` runs both and returns the combined list, deduped by source_id.

Events are the input to the Stage 1 Haiku relevance filter; their `text` field
is what Haiku reads. The `metadata` field carries non-textual context (commit
SHA, PR number, files changed, author) that downstream stages and the MCP
server attach to atoms as source_refs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SourceType = Literal["git_commit", "pr_description", "pr_review_comment"]


@dataclass(frozen=True)
class RawEvent:
    """One unit of content extracted from a repo's history.

    Idempotency: re-runs identify already-processed events by `source_id`, which
    is globally unique within a single repo's ingest (e.g., 'commit:abc123',
    'pr:7:description', 'pr:7:review:2').
    """

    source_type: SourceType
    source_id: str
    timestamp: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def ingest_repo(repo_path: str | Path) -> list[RawEvent]:
    """Run all adapters and return the combined event list, deduped by source_id."""
    from contextlayer.ingest import git_log, gh_prs

    events: list[RawEvent] = []
    seen: set[str] = set()
    for src in (git_log.ingest(repo_path), gh_prs.ingest(repo_path)):
        for evt in src:
            if evt.source_id in seen:
                continue
            seen.add(evt.source_id)
            events.append(evt)
    return events

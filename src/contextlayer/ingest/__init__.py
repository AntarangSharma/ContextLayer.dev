"""Ingestion: convert a repo's history + code into RawEvent records.

Three adapters:
    git_log     — one RawEvent per commit (source_type='git_commit')
    gh_prs      — PR descriptions + review comments (synthetic-shim or gh CLI)
    code_scan   — manifests, docs, top-N source files (source_type='code_scan')

`ingest_repo(path)` runs all three and returns the combined list, deduped by source_id.
`ingest_repo_scan_only(path)` runs only code_scan (for repos without rich git/PR history).

Events are the input to the Stage 1 Haiku relevance filter; their `text` field
is what Haiku reads. The `metadata` field carries non-textual context (commit
SHA, PR number, files changed, author) that downstream stages and the MCP
server attach to atoms as source_refs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SourceType = Literal["git_commit", "pr_description", "pr_review_comment", "code_scan"]


@dataclass(frozen=True)
class RawEvent:
    """One unit of content extracted from a repo's history.

    Idempotency: re-runs identify already-processed events by `source_id`, which
    is globally unique within a single repo's ingest (e.g., 'commit:abc123',
    'pr:7:description', 'pr:7:review:2', 'manifest:pyproject.toml',
    'file:src/api/users.py').
    """

    source_type: SourceType
    source_id: str
    timestamp: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _combine(sources, dedup_set: set[str]) -> list[RawEvent]:
    """Flatten event iterables, deduping by source_id."""
    out: list[RawEvent] = []
    for src in sources:
        for evt in src:
            if evt.source_id in dedup_set:
                continue
            dedup_set.add(evt.source_id)
            out.append(evt)
    return out


def ingest_repo(repo_path: str | Path) -> list[RawEvent]:
    """Run git + PR + code_scan adapters; deduped combined event list."""
    from contextlayer.ingest import git_log, gh_prs, code_scan

    seen: set[str] = set()
    # Each adapter is wrapped in a try/except so a broken adapter doesn't kill the run.
    # code_scan is most likely to fail on weird repos; we keep going if it does.
    out: list[RawEvent] = []
    for adapter_name, adapter_fn in (
        ("git_log", git_log.ingest),
        ("gh_prs", gh_prs.ingest),
        ("code_scan", code_scan.ingest),
    ):
        try:
            out.extend(_combine([adapter_fn(repo_path)], seen))
        except Exception as e:
            # Log to stderr — pipeline still proceeds with whatever did succeed.
            import sys
            sys.stderr.write(f"[ingest:{adapter_name}] failed: {e}\n")
    return out


def ingest_repo_scan_only(repo_path: str | Path) -> list[RawEvent]:
    """Run only code_scan. For repos with no useful git/PR history."""
    from contextlayer.ingest import code_scan

    seen: set[str] = set()
    return _combine([code_scan.ingest(repo_path)], seen)

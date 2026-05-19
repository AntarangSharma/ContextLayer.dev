"""git log adapter — implemented at T+4 (Phase 1 ingestion)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RawEvent:
    """Uniform shape across ingestion sources."""
    source_type: str   # "git_commit" | "pr_description" | "pr_review_comment"
    source_id: str
    timestamp: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


def ingest(repo_path: str) -> list[RawEvent]:
    """Stub. Will subprocess `git log` and parse into RawEvents."""
    raise NotImplementedError("ingest.git_log.ingest — implemented at T+4")

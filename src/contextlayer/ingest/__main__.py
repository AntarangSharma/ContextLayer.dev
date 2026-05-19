"""Smoke runner: `python -m contextlayer.ingest <repo>` prints event counts + samples."""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

from contextlayer.ingest import ingest_repo


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python -m contextlayer.ingest <repo_path>", file=sys.stderr)
        return 2
    events = ingest_repo(Path(argv[1]))
    by_type = Counter(e.source_type for e in events)
    print(f"Ingested {len(events)} events from {argv[1]}:")
    for kind in ("git_commit", "pr_description", "pr_review_comment"):
        print(f"  {kind:24s} {by_type.get(kind, 0):4d}")
    print()
    print("Sample (first 3):")
    for e in events[:3]:
        text_preview = e.text.replace("\n", " ⏎ ")[:90]
        print(f"  [{e.source_type:20s}] {e.source_id}")
        print(f"     ts: {e.timestamp}  meta_keys: {sorted(e.metadata.keys())}")
        print(f"     text: {text_preview!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

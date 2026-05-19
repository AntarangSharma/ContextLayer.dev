"""Resolve a repo path → stable SHA1 hash → SQLite DB location.

Same repo cloned to different paths shares an index (via remote URL hashing).
Repos without a remote fall back to absolute-path hashing (still stable per machine).
"""
from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path


def _get_remote_url(repo_path: Path) -> str | None:
    """Return `origin` URL if it exists, else None."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=repo_path, capture_output=True, text=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def repo_hash(repo_path: str | Path) -> str:
    """Return a stable 12-hex-char hash for this repo."""
    repo_path = Path(repo_path).resolve()
    remote = _get_remote_url(repo_path)
    key = remote if remote else str(repo_path)
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def index_db_path(repo_path: str | Path) -> Path:
    """~/.contextlayer/<hash>/index.db. Creates parent dir on first call."""
    base = Path(os.environ.get("CONTEXTLAYER_HOME", Path.home() / ".contextlayer"))
    db_dir = base / repo_hash(repo_path)
    db_dir.mkdir(parents=True, exist_ok=True)
    return db_dir / "index.db"

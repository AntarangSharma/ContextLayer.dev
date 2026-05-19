"""SQLite WAL-mode atom + embedding store. Implemented at T+8 (Phase 1 store)."""
from __future__ import annotations

from pathlib import Path


def open_db(db_path: str | Path):
    """Stub. Will open SQLite with PRAGMA journal_mode=WAL and ensure schema."""
    raise NotImplementedError("store.sqlite.open_db — implemented at T+8")

"""SQLite WAL-mode atom + embedding store. Per spec §5.4."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

import numpy as np

from contextlayer.extract.atom import Atom

log = logging.getLogger(__name__)

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS atoms (
    id           TEXT PRIMARY KEY,
    category     TEXT NOT NULL,
    summary      TEXT NOT NULL,
    rationale    TEXT,
    scope        TEXT,
    source_refs  TEXT NOT NULL,    -- JSON array
    confidence   REAL NOT NULL,
    is_rule      INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_atoms_category ON atoms(category);
CREATE INDEX IF NOT EXISTS idx_atoms_is_rule ON atoms(is_rule);

CREATE TABLE IF NOT EXISTS atom_embeddings (
    atom_id      TEXT PRIMARY KEY REFERENCES atoms(id) ON DELETE CASCADE,
    vector       BLOB NOT NULL    -- float32 packed
);

CREATE TABLE IF NOT EXISTS topics (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    summary      TEXT,
    atom_ids     TEXT NOT NULL    -- JSON array
);

CREATE TABLE IF NOT EXISTS ingest_cache (
    source_id    TEXT PRIMARY KEY,
    source_type  TEXT NOT NULL,
    stage1_result TEXT,            -- JSON
    stage2_result TEXT,            -- JSON
    processed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT NOT NULL
);
"""


def open_db(db_path: str | Path) -> sqlite3.Connection:
    """Open SQLite with WAL + ensured schema."""
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA_SQL)
    conn.commit()
    return conn


def insert_atom(conn: sqlite3.Connection, atom: Atom, embedding: np.ndarray) -> None:
    """Insert (or ignore on conflict) one atom + its embedding."""
    if atom.id is None or atom.source_refs is None or atom.created_at is None:
        raise ValueError("Atom must have id, source_refs, created_at before storage")
    if embedding.dtype != np.float32:
        embedding = embedding.astype(np.float32)
    conn.execute(
        """INSERT OR IGNORE INTO atoms
           (id, category, summary, rationale, scope, source_refs, confidence, is_rule, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            atom.id, atom.category, atom.summary, atom.rationale, atom.scope,
            json.dumps(atom.source_refs), atom.confidence, int(atom.is_rule),
            atom.created_at,
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO atom_embeddings (atom_id, vector) VALUES (?, ?)",
        (atom.id, embedding.tobytes()),
    )


def list_atoms(conn: sqlite3.Connection) -> list[dict]:
    """Return all atoms as plain dicts."""
    rows = conn.execute(
        "SELECT id, category, summary, rationale, scope, source_refs, confidence, "
        "is_rule, created_at FROM atoms"
    ).fetchall()
    out = []
    for r in rows:
        out.append({
            "id": r[0],
            "category": r[1],
            "summary": r[2],
            "rationale": r[3],
            "scope": r[4],
            "source_refs": json.loads(r[5]),
            "confidence": r[6],
            "is_rule": bool(r[7]),
            "created_at": r[8],
        })
    return out


def all_embeddings(conn: sqlite3.Connection) -> tuple[list[str], np.ndarray]:
    """Return (ids, (N, 384) matrix)."""
    rows = conn.execute("SELECT atom_id, vector FROM atom_embeddings").fetchall()
    if not rows:
        return [], np.zeros((0, 384), dtype=np.float32)
    ids = [r[0] for r in rows]
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return ids, matrix


def insert_topic(
    conn: sqlite3.Connection,
    topic_id: str,
    name: str,
    summary: str,
    atom_ids: list[str],
) -> None:
    """Insert (or replace) a topic row."""
    conn.execute(
        "INSERT OR REPLACE INTO topics (id, name, summary, atom_ids) VALUES (?, ?, ?, ?)",
        (topic_id, name, summary, json.dumps(atom_ids)),
    )


def clear_pipeline_atoms(conn: sqlite3.Connection) -> None:
    """Drop pipeline-produced atoms (preserves user_decision atoms from `contextlayer note`).

    Use before writing a fresh canonical atom set from Stage 3 Opus, so re-indexing
    doesn't accumulate stale duplicates but also doesn't destroy user-authored notes.
    """
    conn.execute(
        "DELETE FROM atom_embeddings WHERE atom_id IN "
        "(SELECT id FROM atoms WHERE category != 'user_decision')"
    )
    conn.execute("DELETE FROM atoms WHERE category != 'user_decision'")
    conn.execute("DELETE FROM topics")


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None

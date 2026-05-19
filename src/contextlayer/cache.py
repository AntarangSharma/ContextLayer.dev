"""In-process cache for the retrieval matrix.

Today the hot path reopens SQLite and reloads every embedding on every
query. For a warm session that's pure waste. We cache `(ids, normalized
matrix, atoms_by_id)` keyed by `(db_path, mtime_ns, size)` so the cache
invalidates automatically when the index changes on disk.

Pre-normalizing the matrix here also lets the query path skip per-call
row-norm computation.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

import numpy as np

from contextlayer.store import sqlite as sqlite_store

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[tuple[int, int], list[str], np.ndarray, dict[str, dict]]] = {}


def _signature(db_path: Path) -> tuple[int, int]:
    st = db_path.stat()
    return (st.st_mtime_ns, st.st_size)


def load(db_path: Path) -> tuple[list[str], np.ndarray, dict[str, dict[str, Any]]]:
    """Return cached `(ids, normalized_matrix, atoms_by_id)` for `db_path`.

    Invalidates and reloads on file mtime/size change. Thread-safe.
    """
    db_path = Path(db_path).resolve()
    key = str(db_path)
    sig = _signature(db_path)

    cached = _CACHE.get(key)
    if cached is not None and cached[0] == sig:
        _, ids, mat, by_id = cached
        return ids, mat, by_id

    with _LOCK:
        cached = _CACHE.get(key)
        if cached is not None and cached[0] == sig:
            _, ids, mat, by_id = cached
            return ids, mat, by_id

        conn = sqlite_store.open_db(db_path)
        try:
            ids, matrix = sqlite_store.all_embeddings(conn)
            atoms_list = sqlite_store.list_atoms(conn)
        finally:
            conn.close()

        if len(ids) == 0:
            normalized = np.zeros((0, 0), dtype=np.float32)
        else:
            norms = np.linalg.norm(matrix, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            normalized = (matrix / norms).astype(np.float32)

        by_id = {a["id"]: a for a in atoms_list}
        _CACHE[key] = (sig, ids, normalized, by_id)
        log.debug("retrieval cache loaded: %s (%d atoms)", db_path, len(ids))
        return ids, normalized, by_id


def invalidate(db_path: Path | None = None) -> None:
    """Drop one (or all) cache entries. Mostly for tests."""
    with _LOCK:
        if db_path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(str(Path(db_path).resolve()), None)

"""End-to-end extraction pipeline orchestrator (Phase 1 MVP).

  ingest events
    → Stage 1 Haiku (per-event, concurrency=2, rate-limited)   — drop irrelevant
    → Stage 2 Sonnet (per-event, concurrency=2, rate-limited)  — extract atoms via tool use
    → In-Python dedup by (summary lower, source_refs)
    → fastembed for each atom
    → SQLite store with WAL

Phase 2 polish (T+14 onwards) adds: Stage 3 Opus extended thinking,
prompt caching, Sonnet batching, idempotency cache, hybrid retrieval.

Rate limits: the proxy in use (api.vibetoken.lol) caps at 60 RPM. We rate-limit
globally to 50 RPM via a token-bucket. Override with CONTEXTLAYER_RPM_LIMIT.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path

import anthropic

from contextlayer.embed import embed_one
from contextlayer.extract import stage1_haiku, stage2_sonnet
from contextlayer.extract.atom import Atom
from contextlayer.extract.stage1_haiku import Stage1Result, classify_one
from contextlayer.extract.stage2_sonnet import extract_one
from contextlayer.extract.stage3_opus import structure_atoms
from contextlayer.ingest import RawEvent, ingest_repo, ingest_repo_scan_only
from contextlayer.store import sqlite as sqlite_store
from contextlayer.store.repo_hash import index_db_path

log = logging.getLogger(__name__)

# Configurable via env (defaults conservative for the api.vibetoken.lol proxy).
RPM_LIMIT = int(os.environ.get("CONTEXTLAYER_RPM_LIMIT", "50"))
STAGE1_CONCURRENCY = int(os.environ.get("CONTEXTLAYER_STAGE1_CONCURRENCY", "2"))
STAGE2_CONCURRENCY = int(os.environ.get("CONTEXTLAYER_STAGE2_CONCURRENCY", "2"))


class GlobalRateLimiter:
    """Token-bucket-ish async rate limiter. Serializes calls to <= rpm per minute."""

    def __init__(self, rpm: int) -> None:
        self.interval = 60.0 / max(rpm, 1)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self.interval - (now - self._last)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


async def _stage1(
    client: anthropic.AsyncAnthropic,
    events: list[RawEvent],
    limiter: GlobalRateLimiter,
    *,
    concurrency: int = STAGE1_CONCURRENCY,
) -> list[tuple[RawEvent, Stage1Result]]:
    """Run Haiku on every event with bounded concurrency + global RPM limit."""
    sem = asyncio.Semaphore(concurrency)
    results: list[tuple[RawEvent, Stage1Result]] = []

    async def one(e: RawEvent) -> None:
        async with sem:
            await limiter.acquire()
            try:
                r = await classify_one(client, e)
            except Exception as ex:
                log.warning("Stage1 failed for %s: %s", e.source_id, ex)
                return
        if r.keep:
            results.append((e, r))

    await asyncio.gather(*(one(e) for e in events))
    return results


async def _stage2(
    client: anthropic.AsyncAnthropic,
    kept: list[tuple[RawEvent, Stage1Result]],
    limiter: GlobalRateLimiter,
    *,
    concurrency: int = STAGE2_CONCURRENCY,
) -> list[Atom]:
    """Run Sonnet on every kept event with bounded concurrency + global RPM limit."""
    sem = asyncio.Semaphore(concurrency)
    atoms: list[Atom] = []

    async def one(e: RawEvent) -> None:
        async with sem:
            await limiter.acquire()
            try:
                xs = await extract_one(client, e)
            except Exception as ex:
                log.warning("Stage2 failed for %s: %s", e.source_id, ex)
                return
        atoms.extend(xs)

    await asyncio.gather(*(one(e) for e, _ in kept))
    return atoms


def _dedupe(atoms: list[Atom]) -> list[Atom]:
    """MVP dedup: by lowercase summary. Phase 2 Stage 3 Opus does smarter conflict resolution."""
    seen: set[str] = set()
    unique: list[Atom] = []
    for a in atoms:
        key = a.summary.lower().strip()
        if key in seen:
            continue
        seen.add(key)
        unique.append(a)
    return unique


def _index_atoms(conn, atoms: list[Atom]) -> int:
    """Embed each atom (summary + rationale) and insert into SQLite."""
    written = 0
    for a in atoms:
        text = a.summary
        if a.rationale:
            text = f"{a.summary}. {a.rationale}"
        vec = embed_one(text)
        sqlite_store.insert_atom(conn, a, vec)
        written += 1
    conn.commit()
    return written


async def _run_extraction(
    events: list[RawEvent],
    repo_path: Path,
    t0: float,
) -> dict:
    """Shared core: events → Haiku → Sonnet → Opus (dedup + topics + rules) → embed → SQLite.

    If Stage 3 Opus fails (e.g., rate limit, API error), fall back to Python dedup
    so we never lose Stage 2 output.
    """
    client = anthropic.AsyncAnthropic()
    limiter = GlobalRateLimiter(rpm=RPM_LIMIT)

    # Reset cumulative cache-hit counters so this run's stats are clean.
    stage1_haiku.reset_usage()
    stage2_sonnet.reset_usage()

    log.info("Stage 1 Haiku — filtering %d events (RPM=%d)...", len(events), RPM_LIMIT)
    kept = await _stage1(client, events, limiter)
    log.info("Haiku kept %d / %d events", len(kept), len(events))

    log.info("Stage 2 Sonnet — extracting atoms from %d events (RPM=%d)...", len(kept), RPM_LIMIT)
    raw_atoms = await _stage2(client, kept, limiter)
    log.info("Sonnet extracted %d raw atoms", len(raw_atoms))

    # Stage 3 — Opus with extended thinking. Falls back to Python dedup on failure.
    canonical_atoms: list[Atom] = []
    topics: list = []
    stage3_ok = False
    if raw_atoms:
        try:
            await limiter.acquire()
            result = await structure_atoms(client, raw_atoms)
            canonical_atoms = result.canonical_atoms
            topics = result.topics
            stage3_ok = True
            log.info(
                "Stage 3 Opus → %d canonical atoms, %d topics, %d rules promoted",
                len(canonical_atoms),
                len(topics),
                sum(1 for a in canonical_atoms if a.is_rule),
            )
        except Exception as e:
            log.warning("Stage 3 Opus failed (%s) — falling back to Python dedup.", e)

    if not stage3_ok:
        canonical_atoms = _dedupe(raw_atoms)
        topics = []
        log.info("Python dedup → %d unique atoms (no topic clustering)", len(canonical_atoms))

    db_path = index_db_path(repo_path)
    conn = sqlite_store.open_db(db_path)
    try:
        # Fresh canonical set replaces previous pipeline atoms (preserves user notes).
        sqlite_store.clear_pipeline_atoms(conn)
        written = _index_atoms(conn, canonical_atoms)
        for t in topics:
            sqlite_store.insert_topic(
                conn,
                topic_id=t.get("id", "t_other"),
                name=t.get("name", "Other"),
                summary=t.get("summary", ""),
                atom_ids=t.get("atom_ids", []),
            )
        sqlite_store.set_meta(conn, "last_indexed_at", str(time.time()))
        sqlite_store.set_meta(conn, "repo_path", str(repo_path))
        sqlite_store.set_meta(conn, "stage3_status", "opus" if stage3_ok else "python_dedup_fallback")
        conn.commit()
    finally:
        conn.close()

    stage1_usage = stage1_haiku.get_usage()
    stage2_usage = stage2_sonnet.get_usage()
    return {
        "repo_path": str(repo_path),
        "db_path": str(db_path),
        "ingested": len(events),
        "kept_after_stage1": len(kept),
        "atoms_after_stage2": len(raw_atoms),
        "atoms_written": written,
        "topics_written": len(topics),
        "rules_promoted": sum(1 for a in canonical_atoms if a.is_rule),
        "stage3_status": "opus" if stage3_ok else "python_dedup_fallback",
        "stage1_usage": stage1_usage,
        "stage2_usage": stage2_usage,
        "cache_read_tokens": stage1_usage["cache_read"] + stage2_usage["cache_read"],
        "cache_write_tokens": stage1_usage["cache_write"] + stage2_usage["cache_write"],
        "elapsed_seconds": round(time.time() - t0, 1),
    }


async def run_pipeline(repo_path: str | Path) -> dict:
    """End-to-end full pipeline: git + PR + code_scan → atoms → SQLite."""
    t0 = time.time()
    repo_path = Path(repo_path).resolve()
    log.info("Pipeline starting on %s (full: git + PR + code_scan)", repo_path)

    events = ingest_repo(repo_path)
    log.info("Ingested %d events from all adapters", len(events))
    return await _run_extraction(events, repo_path, t0)


async def run_pipeline_scan_only(repo_path: str | Path) -> dict:
    """Scan-only pipeline (spec §5.7.1): code_scan only, no git/PR. For repos
    without rich history or where the user just wants atoms from the code."""
    t0 = time.time()
    repo_path = Path(repo_path).resolve()
    log.info("Pipeline starting on %s (scan-only: code_scan)", repo_path)

    events = ingest_repo_scan_only(repo_path)
    log.info("Ingested %d events from code_scan", len(events))
    return await _run_extraction(events, repo_path, t0)

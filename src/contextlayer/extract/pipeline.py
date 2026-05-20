"""End-to-end extraction pipeline orchestrator.

  ingest events
    → Stage 1 Haiku (batched, rate-limited)   — drop irrelevant
    → Stage 2 Sonnet (batched, rate-limited)  — extract atoms via tool use
    → Stage 3 Opus  (single call, extended thinking) — dedup + topics + rules
    → In-Python dedup by (summary lower, source_refs)
    → fastembed for each atom
    → SQLite store with WAL

Production polish on top of the base shape: Stage 3 Opus extended thinking,
prompt caching on cacheable prefixes, Sonnet/Haiku batching, an idempotency
cache so re-runs are near-free, and the hybrid retrieval index.

Rate limits: we rate-limit globally to 50 RPM via a token-bucket so we stay
under conservative per-account caps. Override with CONTEXTLAYER_RPM_LIMIT.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import anthropic

from contextlayer.embed import embed_one
from contextlayer.extract import stage1_haiku, stage2_sonnet
from contextlayer.extract.atom import Atom
from contextlayer.extract.stage1_haiku import Stage1Result, classify_one
from contextlayer.extract.stage2_sonnet import extract_batch, extract_one
from contextlayer.extract.stage3_opus import structure_atoms
from contextlayer.ingest import RawEvent, ingest_repo, ingest_repo_scan_only
from contextlayer.store import sqlite as sqlite_store
from contextlayer.store.repo_hash import index_db_path

log = logging.getLogger(__name__)

# Configurable via env (conservative defaults that stay under typical per-account caps).
RPM_LIMIT = int(os.environ.get("CONTEXTLAYER_RPM_LIMIT", "50"))
STAGE1_CONCURRENCY = int(os.environ.get("CONTEXTLAYER_STAGE1_CONCURRENCY", "2"))
STAGE2_CONCURRENCY = int(os.environ.get("CONTEXTLAYER_STAGE2_CONCURRENCY", "2"))
# Sonnet batching: one Sonnet call extracts atoms from up to N events.
# 15 is the spec default; set to 1 via env to disable and use per-event calls
# (useful if a batched run shows a quality regression vs single-event extraction).
STAGE2_BATCH_SIZE = int(os.environ.get("CONTEXTLAYER_STAGE2_BATCH_SIZE", "15"))


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
    batch_size: int = STAGE2_BATCH_SIZE,
) -> list[Atom]:
    """Run Sonnet on every kept event with bounded concurrency + global RPM limit.

    Batching: when batch_size > 1, group `batch_size` events per Sonnet call
    and use the STAGE2_BATCH_TOOL. On batch failure, fall back to single-event
    extract_one calls for that batch so we don't lose all 15 events to one
    transient API blip.

    Set CONTEXTLAYER_STAGE2_BATCH_SIZE=1 to revert to pure single-event extraction
    (useful for A/B'ing atom quality before/after batching).
    """
    sem = asyncio.Semaphore(concurrency)
    atoms: list[Atom] = []
    events = [e for e, _ in kept]

    if batch_size <= 1:
        log.info("Stage 2: per-event mode (batch_size=1)")
        async def one(e: RawEvent) -> None:
            async with sem:
                await limiter.acquire()
                try:
                    xs = await extract_one(client, e)
                except Exception as ex:
                    log.warning("Stage2 failed for %s: %s", e.source_id, ex)
                    return
            atoms.extend(xs)
        await asyncio.gather(*(one(e) for e in events))
        return atoms

    # Batched path.
    chunks = [events[i : i + batch_size] for i in range(0, len(events), batch_size)]
    log.info(
        "Stage 2: batched mode (%d events → %d batches of up to %d)",
        len(events), len(chunks), batch_size,
    )

    async def one_batch(chunk: list[RawEvent]) -> None:
        async with sem:
            await limiter.acquire()
            try:
                xs = await extract_batch(client, chunk)
                atoms.extend(xs)
                return
            except Exception as ex:
                log.warning(
                    "Stage2 BATCH failed (%d events: %s..) — falling back to single-event calls. err=%s",
                    len(chunk), chunk[0].source_id if chunk else "?", ex,
                )
        # Fallback path: per-event calls for the failed batch, still inside the limiter.
        for e in chunk:
            await limiter.acquire()
            try:
                xs = await extract_one(client, e)
                atoms.extend(xs)
            except Exception as ex:
                log.warning("Stage2 fallback single-call failed for %s: %s", e.source_id, ex)

    await asyncio.gather(*(one_batch(c) for c in chunks))
    return atoms


def _dedupe(atoms: list[Atom]) -> list[Atom]:
    """Fast dedup by lowercase summary. Stage 3 Opus does smarter conflict resolution downstream."""
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


def _split_by_cache(
    conn,
    events: list[RawEvent],
) -> tuple[list[RawEvent], list[Atom], int]:
    """Partition events into (miss, cached_atoms, n_kept_discards).

    For each event:
      - full cache hit + kept=True + stage2 atoms → atoms loaded from cache
      - full cache hit + kept=False → contributed 0 atoms (counted, no API call)
      - miss or partial → returned in `miss` list, will be re-run end-to-end
    """
    miss: list[RawEvent] = []
    cached_atoms: list[Atom] = []
    kept_discards = 0
    for e in events:
        s1, s2 = sqlite_store.get_cached_event(conn, e.source_id)
        if s1 is None:
            miss.append(e)
            continue
        if not s1.get("keep", False):
            # cached as a discard — no atoms, no API call
            kept_discards += 1
            continue
        if s2 is None:
            # partial: kept in Stage 1 but Stage 2 never completed → re-run
            miss.append(e)
            continue
        # Full hit. Rehydrate Atom objects from cached dicts.
        for atom_dict in s2:
            try:
                a = Atom(**atom_dict)
                # Cached atoms already have id/source_refs/created_at populated.
                cached_atoms.append(a)
            except Exception as ex:
                log.warning("Cached atom for %s failed to rehydrate: %s", e.source_id, ex)
    return miss, cached_atoms, kept_discards


async def _run_extraction(
    events: list[RawEvent],
    repo_path: Path,
    t0: float,
) -> dict:
    """Shared core: events → Haiku → Sonnet → Opus (dedup + topics + rules) → embed → SQLite.

    Idempotency cache: events already processed in a previous run are skipped
    — their Stage 1 + Stage 2 results are loaded from ingest_cache so we make
    zero API calls for them. Stage 3 Opus always re-runs on the full (cached
    + fresh) atom set so dedup/topics/rules reflect the current state.

    If Stage 3 Opus fails (e.g., rate limit, API error), fall back to Python dedup
    so we never lose Stage 2 output.
    """
    client = anthropic.AsyncAnthropic()
    limiter = GlobalRateLimiter(rpm=RPM_LIMIT)

    # Reset cumulative cache-hit counters so this run's stats are clean.
    stage1_haiku.reset_usage()
    stage2_sonnet.reset_usage()

    # Open the DB early so we can do idempotency cache lookups + writes during the run.
    db_path = index_db_path(repo_path)
    conn = sqlite_store.open_db(db_path)

    # ----- Idempotency cache lookup -----
    miss_events, cached_atoms, kept_discards = _split_by_cache(conn, events)
    n_cache_hits = len(events) - len(miss_events)
    log.info(
        "Idempotency cache: %d/%d events cached (%d → %d atoms loaded; %d cached-as-discard), "
        "%d to process",
        n_cache_hits, len(events),
        n_cache_hits - kept_discards, len(cached_atoms), kept_discards,
        len(miss_events),
    )

    log.info("Stage 1 Haiku — filtering %d events (RPM=%d)...", len(miss_events), RPM_LIMIT)
    kept = await _stage1(client, miss_events, limiter)
    log.info("Haiku kept %d / %d miss-events", len(kept), len(miss_events))

    # Persist Stage 1 results (both keeps and discards) so a future rerun can skip them.
    kept_ids = {e.source_id for e, _ in kept}
    for e in miss_events:
        if e.source_id in kept_ids:
            r = next(r for ev, r in kept if ev.source_id == e.source_id)
            sqlite_store.cache_stage1(
                conn, e.source_id, e.source_type,
                {"keep": True, "category": r.category},
            )
        else:
            sqlite_store.cache_stage1(
                conn, e.source_id, e.source_type,
                {"keep": False, "category": "none"},
            )
    conn.commit()

    log.info("Stage 2 Sonnet — extracting atoms from %d events (RPM=%d)...", len(kept), RPM_LIMIT)
    fresh_atoms = await _stage2(client, kept, limiter)
    log.info("Sonnet extracted %d fresh atoms (+ %d from cache)", len(fresh_atoms), len(cached_atoms))

    # Persist Stage 2 results per-source_id (group fresh_atoms by source_refs[0]).
    atoms_by_sid: dict[str, list[dict]] = {}
    for a in fresh_atoms:
        if not a.source_refs:
            continue
        sid = a.source_refs[0]
        atoms_by_sid.setdefault(sid, []).append(a.model_dump())
    # Every kept event needs a stage2_result row, even if it produced 0 atoms,
    # so we don't keep re-running events that genuinely have no atoms.
    for e, _ in kept:
        sqlite_store.cache_stage2(conn, e.source_id, atoms_by_sid.get(e.source_id, []))
    conn.commit()

    # ----- Stage 3 input is union of cached + fresh atoms -----
    raw_atoms = cached_atoms + fresh_atoms
    log.info("Stage 3 input: %d raw atoms (cached=%d, fresh=%d)",
             len(raw_atoms), len(cached_atoms), len(fresh_atoms))

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

    try:
        # Fresh canonical set replaces previous pipeline atoms (preserves user notes
        # AND preserves the ingest_cache — it's intentionally NOT cleared, so reruns
        # skip API calls).
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
        sqlite_store.set_meta(
            conn,
            "last_indexed_at",
            datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
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
        "events_cache_hit": n_cache_hits,
        "events_cache_miss": len(miss_events),
        "kept_after_stage1": len(kept),
        "atoms_after_stage2": len(raw_atoms),
        "atoms_fresh": len(fresh_atoms),
        "atoms_from_cache": len(cached_atoms),
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

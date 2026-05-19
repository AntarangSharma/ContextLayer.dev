# Session Handoff — 2026-05-18

**Phase 1 ✅ done (T+0 → T+14).** **Phase 2A in progress (T+14 → T+21): solo-dev features per spec §5.7.** **Phase 2B (T+21 → T+35): pipeline polish.** See `tasks/todo.md` for the live plan.

**Spec updated 2026-05-18:** commit `4becdd5` added §5.7 with five new features (3 build in Phase 2A, 2 designed for v1.1). The `note` → `explain` → `scan` build order is locked.

---

## Where the project stands

✅ **End-to-end MVP demo works.** `contextlayer index` → 67 atoms in SQLite. `contextlayer mcp` starts a stdio MCP server. The server responds to `initialize`, `tools/list`, and `tools/call` correctly. The locked demo question (Q1 — "I need to add an endpoint that fetches a user's billing history") returns 5 cited atoms.

### Latest commits
```
c6b6b72 T+13: MCP server (FastMCP on official MCP Python SDK)
4bec37b T+8:  MVP extraction pipeline (Haiku + Sonnet + fastembed + SQLite)
01f967b T+4:  Ingestion adapters (git log + synthetic PR shim)
fc67859 T+2:  Synthetic demo repo generator (15 PRs, deliberate conventions)
4e47db9 T+0:  Project skeleton (uv + typer + mcp + anthropic + fastembed)
```

### Reproduce from a fresh checkout
```bash
git clone https://github.com/AntarangSharma/ContextLayer.dev.git
cd ContextLayer.dev
export PATH="/Users/antarangsharma/.local/bin:/opt/homebrew/bin:$PATH"   # uv, gh, brew
uv sync                                           # installs deps (one-time)
uv run python demo-data/build_acme.py             # generates synthetic repo + .mcp.json + CLAUDE.md
uv run contextlayer index demo-data/acme-billing-api   # ~3.5 min, ~$0.30 API spend
uv run contextlayer status --repo demo-data/acme-billing-api  # confirms 67 atoms
```

### Environment quirks (must know before resuming)

1. **`ANTHROPIC_API_KEY` is a proxy/router key** with prefix `vt-online-…`, length 51. It routes to `api.vibetoken.lol`, **not** `api.anthropic.com`. Works with the standard `anthropic.Anthropic()` client.
2. **Rate limit: 60 RPM** on the proxy. Pipeline rate-limits to **50 RPM** globally via `GlobalRateLimiter` in `extract/pipeline.py`. Override with `CONTEXTLAYER_RPM_LIMIT`.
3. **Model IDs that resolve on this proxy:**
   - `claude-haiku-4-5` → `claude-haiku-4-5-20251001`
   - `claude-sonnet-4-5` → `claude-sonnet-4-5-20250929`
   - `claude-opus-4-1` → `claude-opus-4-1-20250805`
   - **Do NOT use** `claude-sonnet-4`, `claude-3-5-sonnet-latest`, `claude-opus-4` — not exposed by this proxy
4. **`mcp` is BOTH a top-level dep AND our subcommand.** Our directory is `src/contextlayer/mcp_server/`, not `mcp/`, to avoid shadowing.
5. **`uv init` defaults to Python 3.9 + src/ layout.** We're pinned to 3.11 in `.python-version`.
6. **fastembed downloads ~120 MB on first run** (one time, cached under `~/.cache/huggingface/`).

---

## Resolved decisions (locked, do NOT re-debate)

From `tasks/todo.md` "Resolved decisions" block:

1. **Sleep/breaks** — operator-managed; hours in plan are PRODUCTIVE hours, not calendar hours
2. **T+0** — Mon 2026-05-18 evening (already declared)
3. **Demo question Q1** — "I need to add an endpoint that fetches a user's billing history — show me how." Surfaces ~4 atoms (`Result<T>`, async-first, `Depends(get_session)`, don't-share-session anti-pattern). LOCKED.
4. **Opus in MVP** — SKIPPED in Phase 1, added in Phase 2 (preserves MVP-first guardrail; final output identical because Phase 2 lands before any judge sees anything)
5. **CLAUDE.md nudge** — current version is the strong version (already updated in `demo-data/acme-billing-api/CLAUDE.md` via `build_acme.py`). Adjust further only if Claude Code is unreliable

---

## What Phase 2 needs to do (T+14 → T+28, ~14 productive hours)

Per `tasks/todo.md`. In order:

| Time | Task | Notes |
|---|---|---|
| T+14 → T+16 | **Stage 3 Opus with extended thinking** | Single call, `thinking={"type": "enabled", "budget_tokens": 8000}`. Input = all 67 atoms. Output = deduped atoms (collapse the 5+ Result<T> variants into 1), topic clusters, rule promotion (confidence ≥0.8 → `is_rule=1`). **This is the biggest retrieval-quality win.** |
| T+16 → T+17:30 | Prompt caching (Haiku + Sonnet) | Add `cache_control: {"type": "ephemeral"}` to system prompt. Verify `cache_read_input_tokens > 0` on the second call's `usage` |
| T+17:30 → T+19:30 | Sonnet batching (15 events/call) | Update tool schema to accept `events: list[Event]` and return `atoms: list[Atom]`. Manual quality skim before vs after |
| T+19:30 → T+21 | Idempotency cache wiring | Write `ingest_cache` row on every stage1+stage2 result. Re-running `contextlayer index` should make ~0 API calls. Verify |
| T+21 → T+23 | Hybrid retrieval | `score = 0.4*cosine + 0.4*keyword + 0.2*recency`. Replaces `retrieval.cosine_search`. Token-set Jaccard for keyword; normalized date range for recency |
| T+23 → T+24 | `status` + `claude-md` polish | Both subcommands exist already; verify they reflect Phase 2 fields (topics, rules) |
| T+24 → T+26 | Full re-index + atom audit | Run full pipeline (with all stages, caching, batching). Manually inspect every atom; spot-fix weak ones. Target ≥40 atoms, ≥5 topics, ≥5 rules (success criterion §10) |
| T+26 → T+28 | Demo question verify + commit demo script | Q1 already locked — just verify it surfaces the right 4 atoms after Phase 2 retrieval. Write `docs/demo-script.md` with timing notes |
| **G2 @ T+28** | Stop-and-ship gate | If any Phase 2 component regresses, revert before continuing |

### Known retrieval issue Phase 2 must fix

Currently the locked demo Q1 returns these as top-5:
1. "Async endpoints are permitted; mixing policy pending" (0.660) — weak version of async atom
2. "Sync /billing handlers converted to async, don't revert" (0.657)
3. "Long-running streaming queries don't hold session" (0.656)
4. "Long-running streaming queries..." (0.650) — DUPLICATE of #3 (Opus dedup will fix)
5. "Use HTTPException for 404" (0.642) — **OLDER convention deprecated by PR #6**, this is wrong

The 4 canonical atoms (Result<T>, async-first, Depends, anti-pattern) are in the DB but ranked lower. After Opus dedup + hybrid retrieval, they should dominate the top-5.

---

## How to resume in a fresh session

```
Open the new Claude Code session and say:

  Read /Users/antarangsharma/Documents/ContextLayer.dev/tasks/handoff.md
  and /Users/antarangsharma/Documents/ContextLayer.dev/tasks/todo.md.
  Phase 1 is complete (G1 passed). Resume Phase 2 from T+14:
  Stage 3 Opus with extended thinking.
```

That's all the context the new session needs to start. The spec, plan, and code carry the rest.

---

## File map (key files)

```
docs/specs/2026-05-18-contextlayer-design.md   ← design spec (locked, 18 hardenings)
tasks/todo.md                                  ← 48h plan (resolved decisions block at top)
tasks/handoff.md                               ← this file
tasks/lessons.md                               ← captured learnings
src/contextlayer/cli.py                        ← typer entry: index, mcp, status, claude-md
src/contextlayer/models.py                     ← claude-haiku-4-5, claude-sonnet-4-5, claude-opus-4-1
src/contextlayer/ingest/                       ← git_log + synthetic-PR shim → RawEvents
src/contextlayer/extract/atom.py               ← Pydantic Atom + Stage 1/2 tool schemas
src/contextlayer/extract/stage1_haiku.py       ← per-event filter (Phase 2: add caching + batching)
src/contextlayer/extract/stage2_sonnet.py      ← per-event extractor with tool use
src/contextlayer/extract/stage3_opus.py        ← STUB — implement at T+14
src/contextlayer/extract/pipeline.py           ← orchestrator + GlobalRateLimiter (50 RPM)
src/contextlayer/embed.py                      ← fastembed BGE-small-en-v1.5
src/contextlayer/retrieval.py                  ← MVP plain cosine (Phase 2: hybrid at T+21)
src/contextlayer/store/sqlite.py               ← WAL schema (spec §5.4), atom insertion
src/contextlayer/store/repo_hash.py            ← SHA1(remote URL) → ~/.contextlayer/<hash>/
src/contextlayer/mcp_server/server.py          ← FastMCP stdio + context_query + context_list_topics
demo-data/build_acme.py                        ← 15-PR generator + writes .mcp.json + CLAUDE.md after commits
demo-data/acme-billing-api/                    ← (gitignored) — regenerate from build_acme.py
~/.contextlayer/66cb5dd4ff37/index.db          ← 67 atoms + embeddings from Phase 1 run
```

---

## Atoms currently in the DB

67 atoms, 4 critical conventions captured with high confidence:

| Concept | Best atom | Confidence | Source |
|---|---|---|---|
| Result<T> convention | "Domain-level errors (validation, not-found, …) MUST return Result.err(reason), not raise" | 0.95 | pr:3:description |
| async-first decision | "Route handlers that perform I/O MUST be `async def`" | 0.95 | commit:1dc68af |
| db_helper deprecation | "utils/db_helper is deprecated; do not use. Will raise RuntimeError after Sprint 2027-Q1" | 0.98 | pr:8 |
| Anti-pattern | "Never create a module-level SQLAlchemy session" | 0.95 | pr:14 |

Plus 60+ secondary atoms (cache/auth, scope conventions, lint rules, etc.). Phase 2 Opus will collapse duplicates and promote rules.

---

## Cost so far

- Pipeline run on synthetic repo: ~$0.30 (Haiku ~$0.02 + Sonnet ~$0.28)
- Total session API spend: ~$0.30–$0.50 (one full pipeline run + 1 partial pre-rate-limiter run + sanity checks)

Phase 2 will add ~$1 (Opus extended thinking on 67 atoms in one call).


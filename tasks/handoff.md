# Session Handoff — 2026-05-18 (post-polish session)

**Phases 1, 2A, 2B ✅ done. Phase 3 ✅ mostly done — only video + Vercel deploy + clean-machine `uvx` test outstanding.** All three are user-action gates, not code work.

---

## Where the project stands (post no-API polish session)

✅ **End-to-end demo path works locally.** `contextlayer index` produces 15 canonical atoms / 7 topics / 8 rules from the synthetic repo (Opus dedup collapsed 67 raw atoms → 15 high-signal). All 4 demo-critical conventions are present as RULES at confidence ≥0.95:

| Concept | Confidence | is_rule |
|---|---|---|
| Result\<T\> for domain errors | 0.95 | ✓ |
| async-first I/O routes | 0.95 | ✓ |
| db_helper deprecation → Depends(get_session) | 0.95 | ✓ |
| Never share session across requests (anti-pattern) | 0.96 | ✓ |

✅ **Locked demo Q1 surfaces all 4 canonical atoms in top-5** (verified locally via fastembed; no API needed for retrieval). Hybrid retrieval rebalanced post-Opus: `0.45*cos + 0.30*kw + 0.15*rule + 0.10*rec`. The rule-bonus addition fixed a regression where the unrelated `/metrics` atom was dominating top-5 on raw cosine alone.

✅ **MCP server boots cleanly without an Anthropic API key** — confirmed via the new `tests/smoke/test_mcp_server.py` smoke test (subprocess + stdio + initialize + tools/list).

### Latest commits (since the previous handoff)

```
bb666d8  Phase 3: Landing page, README, demo script, MIT license
ed7dae1  T+28: Idempotency cache + hybrid retrieval (cosine+keyword+recency)
d06cd2e  T+24:30: Sonnet batching at 15 events/call (with graceful per-event fallback)
8d7dc6f  T+23: prompt caching on Haiku + Sonnet (system + tools prefix)
fb4420a  T+21: Stage 3 Opus with extended thinking (dedup + topics + rule promotion)
35e63ff  T+18: contextlayer scan (code-aware ingestion, spec §5.7.1)
3b10c75  T+15:30: contextlayer explain (Onboarding Doc generator, spec §5.7.3)
bffc1e6  T+14: contextlayer note (Decision Journal CLI, spec §5.7.2)
```

**Pending uncommitted (this session's work):**

```
M  src/contextlayer/cli.py                      # status now formats last_indexed_at as UTC
M  src/contextlayer/extract/pipeline.py         # writer uses ISO 8601 timestamps going forward
M  src/contextlayer/retrieval.py                # rebalanced weights, +is_rule boost, recency safety net
M  pyproject.toml                               # pytest dev-group + tool config
M  README.md                                    # tweaked architecture diagram, added Development section
M  docs/specs/2026-05-18-contextlayer-design.md # walked §10 success criteria
M  landing/index.html                           # em-dash → hyphen normalization
M  tests/smoke/README.md                        # documented the 2 implemented smoke tests
A  tests/smoke/test_retrieval.py                # NEW — 2 retrieval assertions (no API)
A  tests/smoke/test_mcp_server.py               # NEW — MCP stdio handshake (no API)
A  docs/slide-deck.md                           # NEW — 8-slide deck outline
A  uv.lock                                      # pytest etc.
```

---

## Reproduce from a fresh checkout

```bash
git clone https://github.com/AntarangSharma/ContextLayer.dev.git
cd ContextLayer.dev
uv sync --group dev                                      # installs runtime + pytest
export ANTHROPIC_API_KEY=...                             # required for index/scan, not for mcp/smoke tests
uv run python demo-data/build_acme.py                    # generates synthetic repo
uv run contextlayer index demo-data/acme-billing-api     # ~3.5 min, ~$1.50 API spend (Haiku+Sonnet+Opus)
uv run contextlayer status --repo demo-data/acme-billing-api  # confirms ~15 atoms, 7 topics, 8 rules
uv run pytest tests/smoke -q                             # 3 local smoke tests, no API
```

---

## What still requires user action (not codeable)

| Item | Why it's user-only |
|---|---|
| Demo video record + edit | Operator presence; Claude Code (and the Anthropic API) is exercised |
| Deploy `landing/` to Vercel | Vercel auth + custom domain |
| Publish to PyPI for `uvx contextlayer-dev` | Operator's PyPI token; gates the spec §10 clean-machine criterion. Package is named `contextlayer-dev` (`contextlayer` is taken on PyPI by Autoblocks); CLI binary keeps the `contextlayer` brand command via dual entry-points |
| Submit to hackathon portal | Operator's account |

Everything else that doesn't require an API call (retrieval tuning, smoke tests, status polish, README pass, success-criteria walk, slide-deck commit, atom audit) was completed this session.

---

## Environment quirks (carry forward)

1. **`ANTHROPIC_API_KEY` is a `vt-online-…` proxy key** routing to `api.vibetoken.lol`. Standard `anthropic.Anthropic()` client works.
2. **Rate limit: 60 RPM**; pipeline rate-limits to 50 RPM globally via `GlobalRateLimiter` in `extract/pipeline.py`. Override with `CONTEXTLAYER_RPM_LIMIT`.
3. **Model IDs that resolve on this proxy:**
   - `claude-haiku-4-5` → `claude-haiku-4-5-20251001`
   - `claude-sonnet-4-5` → `claude-sonnet-4-5-20250929`
   - `claude-opus-4-1` → `claude-opus-4-1-20250805`
4. **`mcp` is BOTH a dep AND our subcommand.** Our directory is `src/contextlayer/mcp_server/`, not `mcp/`, to avoid shadowing.
5. **fastembed downloads ~120 MB on first run** (cached under `~/.cache/huggingface/`).

---

## Key files (post-polish state)

```
docs/specs/2026-05-18-contextlayer-design.md   ← design spec (locked, 26 hardenings; §10 success criteria walked)
docs/slide-deck.md                              ← 8-slide deck outline (untracked → committing in final polish)
docs/demo-script.md                             ← 3-min demo flow with pane-A/pane-B beats
tasks/todo.md                                   ← 48h plan (resolved decisions block at top)
tasks/handoff.md                                ← this file
tasks/lessons.md                                ← captured learnings
tests/smoke/test_retrieval.py                   ← Q1 surfaces all 4 canonical atoms (no API)
tests/smoke/test_mcp_server.py                  ← stdio initialize + tools/list (no API)
src/contextlayer/cli.py                         ← typer entry: index/scan/mcp/note/explain/status/claude-md
src/contextlayer/retrieval.py                   ← hybrid scoring (0.45/0.30/0.15/0.10)
src/contextlayer/extract/pipeline.py            ← orchestrator + GlobalRateLimiter (50 RPM) + ISO timestamps
src/contextlayer/extract/stage3_opus.py         ← extended thinking (8000 budget tokens)
src/contextlayer/store/sqlite.py                ← WAL schema (spec §5.4) + meta + ingest_cache
src/contextlayer/mcp_server/server.py           ← FastMCP stdio + context_query + context_list_topics
demo-data/build_acme.py                         ← 15-PR generator + writes .mcp.json + CLAUDE.md
demo-data/acme-billing-api/                     ← (gitignored) — regenerate from build_acme.py
~/.contextlayer/66cb5dd4ff37/index.db           ← 15 atoms / 7 topics / 8 rules from latest run
```

---

## Cost so far

- All Phase 1 + 2A + 2B pipeline runs combined: ~$2–3 of API spend on the proxy
- Phase 2B re-index (Haiku + Sonnet batched + Opus extended thinking) on synthetic repo: ~$1.50

Re-runs are near-free thanks to the `ingest_cache` table.

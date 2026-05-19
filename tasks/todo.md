# 48h Implementation Plan — ContextLayer.dev

**Spec reference:** `docs/specs/2026-05-18-contextlayer-design.md` (Appendix A entries 16–23; new §5.7 solo-dev features)
**Strategy:** MVP-first sequencing — working before/after demo by **T+14 (productive hours)**, solo-dev features T+14 → T+21, pipeline/retrieval polish T+21 → T+35, materials T+35 → T+42, dry runs + submit T+42 → T+46.
**Submission:** Wed 2026-05-20 evening.
**Operator:** solo, BYOK with own `ANTHROPIC_API_KEY`. **T+0 declared: Mon 2026-05-18 evening.**

**Resolved decisions (recorded 2026-05-18):**
- Sleep / breaks: operator-managed, not scheduled. Hours below are productive hours, not calendar hours.
- Wall-clock T+0: Mon 2026-05-18 evening.
- Demo question (locked): **Q1** — *"I need to add an endpoint that fetches a user's billing history — show me how."* Surfaces ~4 atoms in one response (`Result<T>`, async-first, SQLAlchemy session, don't share session) — broadest before/after contrast.
- MVP Opus: skip from MVP, add in Phase 2B. Preserves MVP-first guardrail; final output identical.
- CLAUDE.md nudge: start with spec §5.5 soft nudge; strengthen at T+13 if Claude Code is flaky.

**Phase 1 status (2026-05-18): ✅ COMPLETE — G1 passed.** 67 atoms in DB; MCP server speaks protocol; locked demo Q1 returns 5 cited atoms. Resume from Phase 2A.

**Phase 2 scope expansion (2026-05-18):** Per spec §5.7, three new solo-dev features added to Phase 2A (T+14 → T+21): `contextlayer note`, `contextlayer explain`, `contextlayer scan`. Existing pipeline-polish work becomes Phase 2B (T+21 → T+35). `context_validate` and `contextlayer health` are designed in §5.7.4-5 but ship in v1.1 — do **not** build them this hackathon.

---

## Strategic frame

The linear failure mode for a 48h solo hackathon is: build pipeline → build MCP → wire demo → demo doesn't work until hour 47 → submit broken. We invert: **a working end-to-end demo exists by T+14 even if every component is a mediocre stub**. Polish, prompt caching, batching, extended thinking, hybrid retrieval, landing page, deck, video, FastAPI stretch — all attack a working artifact, not a hypothetical one.

Every phase has a **stop-and-ship gate** that downgrades scope rather than slipping the demo.

```
T+0 ──── T+14 ──── T+21 ────── T+35 ───── T+42 ─── T+46
│ P1:    │ P2A:    │ P2B:      │ P3:      │ P4:    │
│ MVP    │ solo-   │ pipeline  │ demo     │ dry    │
│ demo   │ dev     │ + retr'l  │ materials│ runs + │
│        │ feats   │ polish    │          │ submit │
└────────┴─────────┴───────────┴──────────┴────────┘
   G1                G2          G3         G4
```

---

## Time accounting

**Hours below are PRODUCTIVE hours from your declared T+0** — not calendar hours. You manage breaks, meals, and sleep manually; pause whenever you need to and resume the clock when you're back.

| Quantity | Value |
|---|---|
| Total productive hours in this plan | **46h** (was 40h pre-Phase-2-expansion; +7h for solo-dev features, -1h by tightening dry-run window) |
| Calendar deadline (Wed 2026-05-20 evening) | ~48h |
| Operator-managed slack (breaks, sleep, food, surprises) | **~2h** |

> Slack is now tight. The phase-2 scope expansion ate most of the original 8h buffer. If anything slips, **cut the FastAPI stretch first** (already optional per Appendix A #16). Phase 1 finished ahead of plan, which gave us this room.

---

## PHASE 1 — Working end-to-end MVP (T+0 → T+14)

**Goal:** two-pane demo works on the synthetic `acme-billing-api/` repo. Claude Code A (no MCP) gives a generic answer; Claude Code B (MCP loaded) cites at least one atom with a source ref.

**Exit criteria (G1 at T+14):**
- [ ] `contextlayer index demo-data/acme-billing-api` runs, writes SQLite with ≥20 atoms
- [ ] `contextlayer mcp --repo demo-data/acme-billing-api` starts the stdio server
- [ ] Claude Code, with `.mcp.json` configured, calls `context_query` for the demo question
- [ ] Response cites at least one atom (e.g., `Result<T>` from PR #3)
- [ ] One un-edited recording exists of this happening

### T+0 → T+2 · Project skeleton + deps + secrets
- [ ] `uv init contextlayer` at repo root; commit `pyproject.toml`
- [ ] Package layout: `contextlayer/{__init__,cli,ingest/{git_log,gh_prs},extract/{stage1_haiku,stage2_sonnet,stage3_opus},mcp/server,store/sqlite,retrieval,embed}.py`
- [ ] Deps: `anthropic`, `mcp`, `fastembed`, `numpy`, `typer`, `pydantic`, `python-dotenv` (optional)
- [ ] `demo-data/`, `tests/smoke/`, `landing/`, scaffolds created
- [ ] `.gitignore` adds: `*.db`, `~/.contextlayer/`, `dist/`, `.venv/`, `__pycache__/`, `*.egg-info/`
- [ ] `contextlayer/__main__.py` so `python -m contextlayer` works
- [ ] Sanity: `uv run contextlayer --help` prints typer help
- [ ] **Commit:** `Project skeleton (uv + typer + mcp + anthropic + fastembed)`

### T+2 → T+4 · Synthetic demo repo
- [ ] Write `demo-data/build_acme.py` — deterministic generator producing a 15-commit git repo with structured PR-like commit bodies and "review-comment" notes
- [ ] Conventions to embed:
  - PR #3: adopt `Result<T>` for domain errors
  - PR #6: refactor billing to use `Result<T>` (reinforces #3)
  - PR #8: deprecate `db_helper`, use SQLAlchemy session
  - PR #11: async-first for I/O routes
  - PR #14: anti-pattern — don't share session across requests
  - PRs #1, 2, 4, 5, 7, 9, 10, 12, 13, 15: ordinary work + 1–3 simulated review comments each
- [ ] Generator output: `demo-data/acme-billing-api/` (separate `.git` inside)
- [ ] Add `demo-data/.gitkeep` and document the generator in `demo-data/README.md`
- [ ] **Commit:** `Add synthetic demo repo generator + acme-billing-api`

### T+4 → T+8 · Ingestion adapters
- [ ] `ingest/git_log.py`: subprocess `git log --format='%H|%an|%aI|%s|%b'` + `--name-only`; parse into `RawEvent`
- [ ] `ingest/gh_prs.py`: real `gh pr list --state merged --json ...` path for real repos; for the synthetic repo, a shim that reads commit message bodies as "PR descriptions" and parses git notes as "review comments"
- [ ] `RawEvent` dataclass: `source_type`, `source_id`, `timestamp`, `text`, `metadata: dict`
- [ ] Idempotency cache stub (table exists but not yet wired to skip)
- [ ] Smoke: `python -m contextlayer.ingest.git_log demo-data/acme-billing-api` prints event count
- [ ] **Commit:** `Ingestion adapters: git log + synthetic PR shim`

### T+8 → T+12 · MVP extraction pipeline (Haiku + Sonnet only, **no caching, no batching, no Opus**)
- [ ] `extract/stage1_haiku.py`: single-event Haiku call per event, asyncio.Semaphore(5). Prompt = "Is this a convention/decision/deprecation/anti-pattern? Return JSON `{keep, category}`."
- [ ] `extract/stage2_sonnet.py`: single-event Sonnet call per kept event, using **Anthropic tool use** with the Atom schema. asyncio.Semaphore(3).
- [ ] In-Python dedup: drop atoms with identical `(summary, source_refs)`. **Skip Stage 3 Opus entirely for MVP.**
- [ ] `store/sqlite.py`: WAL mode, the schema from §5.4 minus `topics` table (defer topics to Phase 2)
- [ ] `embed.py`: `fastembed.TextEmbedding("BAAI/bge-small-en-v1.5")`; pack vectors as float32 BLOB
- [ ] Smoke: synthetic repo → ≥20 atoms in DB
- [ ] **Commit:** `MVP extraction pipeline (Haiku→Sonnet, no caching/batching/Opus yet)`
- [ ] **Expected API spend so far on synthetic repo: ~$0.30**

### T+12 → T+13 · CLI: `index` subcommand
- [ ] `cli/__init__.py` with typer: `index`, `mcp`, `status`, `claude-md`
- [ ] `index <repo>` runs ingest → stage1 → stage2 → write
- [ ] DB path: SHA1(remote URL) with absolute-path fallback → `~/.contextlayer/<hash>/index.db`
- [ ] Progress prints: `Haiku filtered X→Y · Sonnet extracted Z atoms`
- [ ] **Commit:** `CLI: index subcommand`

### T+13 → T+13:30 · MCP server (on the MCP Python SDK — adjustment #17)
- [ ] `mcp/server.py` — use `mcp.server.Server` + `mcp.server.stdio.stdio_server`
- [ ] Register two tools with the SDK's `@server.list_tools()` / `@server.call_tool()` (consult the SDK README live; do not improvise)
- [ ] `context_query(question, k=5)`: embed question → numpy cosine over atom vectors → top-k atoms (plain cosine, no reranking yet)
- [ ] `context_list_topics()`: returns an empty list with `{"message": "topics added in Phase 2"}` — placeholder
- [ ] CLI `mcp --repo <path>` starts the stdio server
- [ ] Smoke: `python -m contextlayer mcp --repo demo-data/acme-billing-api` blocks on stdin without error
- [ ] **Commit:** `MCP server on official MCP Python SDK (MVP retrieval)`

### T+13:30 → T+14 · Wire to Claude Code, **end-to-end test**
- [ ] Write `demo-data/.mcp.json` pointing at the synthetic repo
- [ ] Open Claude Code in `demo-data/`, verify the contextlayer server connects
- [ ] Author `demo-data/CLAUDE.md` with the "call `context_query` before proposing changes" snippet
- [ ] Ask the candidate demo question; verify a cited atom appears in the response
- [ ] **If the tool isn't being called**: strengthen the CLAUDE.md nudge; re-test
- [ ] Record a rough Quicktime / OBS screen capture as the **MVP demo artifact** (kept as the always-shippable fallback)
- [ ] **Commit:** `Wire Claude Code MCP config + CLAUDE.md snippet; MVP demo runs end-to-end`

### 🚧 **G1 — STOP-AND-SHIP GATE @ T+14**
If the recorded MVP demo doesn't show a cited atom in Pane B vs no atom in Pane A:
- All Phase 2 hours triage demo blockers (drop Opus, drop caching, drop batching, drop hybrid retrieval, drop FastAPI stretch — only the blocker).
- The MVP recording from T+14 is the worst-case submission artifact.

---

## PHASE 2A — Solo-dev features (T+14 → T+21)

**Goal:** ship `contextlayer note`, `contextlayer explain`, `contextlayer scan` so ContextLayer works on ANY repo, not just teams with mature PR cultures. Per spec §5.7. Build smallest-first to validate the atom-write path early.

**Strategic frame:** without these features, day-one TAM is ~10% of GitHub (mature PR teams). With them, ~100% of GitHub (any solo dev with a Git repo). The features are also load-bearing for the deck's v1.1 roadmap — judges WILL ask "what about repos with no PRs?"

### T+14 → T+15:30 · `contextlayer note` (1.5h) — spec §5.7.2
**Smallest, validates the atom-write path with a user source.**
- [ ] Extend the Atom `category` Literal: add `"user_decision"` alongside the four existing categories
- [ ] Add `cli.note(text, --scope, --rationale, --repo)` subcommand
- [ ] Construct Atom with `category="user_decision"`, `source_refs=["note:<iso-timestamp>"]`, `confidence=1.0`, optional `scope`, optional `rationale`
- [ ] Embed locally with fastembed; insert into atoms + atom_embeddings tables (open_db creates schema if first run)
- [ ] Works even before `contextlayer index` has been run on this repo
- [ ] Smoke: write a note → `context_query` surfaces it in the response
- [ ] **Commit:** `T+14: contextlayer note (Decision Journal CLI, spec §5.7.2)`

### T+15:30 → T+18 · `contextlayer explain` (2.5h) — spec §5.7.3
**Composition of existing pieces, ships an artifact judges can hold.**
- [ ] `uv add jinja2`
- [ ] Create `src/contextlayer/templates/explain.md.j2` with sections: project header, stack (inferred), top conventions, active decisions, anti-patterns, deprecations, topic index
- [ ] Inline stack detection: read `pyproject.toml` / `package.json` / `Cargo.toml` / `go.mod` if present (no Sonnet call needed for this slice)
- [ ] Add `cli.explain(--out, --repo)` subcommand: reads atoms via store, groups by category, sorts (confidence desc; created_at desc for decisions), renders via Jinja2 to stdout or file
- [ ] Smoke: produces a readable markdown brief from the synthetic repo's 67 atoms; ~1-2 page output
- [ ] **Commit:** `T+15:30: contextlayer explain (Onboarding Doc generator, spec §5.7.3)`

### T+18 → T+21 · `contextlayer scan` (3h) — spec §5.7.1
**Biggest TAM unlock — repos with zero PRs now produce atoms.**
- [ ] `src/contextlayer/ingest/code_scan.py`: new RawEvent producer
- [ ] Sources (thin v1 per §5.7.1 table):
  - Manifests: `pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod` → one RawEvent each (`source_type="code_scan"`, `source_id="manifest:<name>"`)
  - Top-level `.md` files: `README.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, etc. → one RawEvent each (`source_id="file:<relpath>"`)
  - File-extension distribution: count `.py`, `.ts`, `.rs`, `.go`, etc. → one summary RawEvent (`source_id="repo-summary"`)
  - Top-20 largest source files (by line count, excluding `.git/`, `__pycache__/`, `node_modules/`, `.venv/`): first ~200 lines each → RawEvent each (`source_id="file:<relpath>"`)
- [ ] Wire `cli.scan(repo)` — runs only code_scan + Haiku/Sonnet pipeline (no git, no PR)
- [ ] Wire `cli.index` to invoke code_scan adapter alongside git_log + gh_prs (additive; spec §5.7.1 says "code_scan events are added to the pipeline run")
- [ ] Smoke: a fresh git repo with zero PRs (e.g., `git init /tmp/fresh && cd /tmp/fresh && echo "# Fresh" > README.md && git add -A && git commit -m "init"`) → `contextlayer scan /tmp/fresh` produces ≥3 atoms
- [ ] **Commit:** `T+18: contextlayer scan (code-aware ingestion, spec §5.7.1)`

### What we deliberately do NOT build in Phase 2A
- `context_validate` (spec §5.7.4) — v1.1; false-positive tuning is a multi-day risk to the demo
- `contextlayer health` (spec §5.7.5) — v1.1; the scorecard is the OSS-launch wedge, not a hackathon piece

Both have full designs already in §5.7.4 / §5.7.5; they live on the deck's roadmap slide.

---

## PHASE 2B — Pipeline + retrieval polish (T+21 → T+35)

**Goal:** the same demo, but with measurably better atoms, faster pipeline, and richer retrieval. The pipeline is now what the judges' "tell me what makes this technically ambitious" question lands on.

### T+21 → T+23 · Stage 3 Opus with extended thinking
- [ ] `extract/stage3_opus.py`: single call, `thinking={"type": "enabled", "budget_tokens": 8000}`
- [ ] Input: all extracted atoms; output: deduped atoms, topic groupings, rule promotion (`confidence ≥ 0.8 → is_rule=1`)
- [ ] Add `topics` table writes
- [ ] Update `context_list_topics()` to return real topics
- [ ] Smoke: synthetic repo run finishes; atoms now have `topic_id`s; ≥3 rules promoted
- [ ] **Commit:** `Stage 3 Opus with extended thinking + topic clustering`

### T+23 → T+24:30 · Prompt caching (Haiku + Sonnet)
- [ ] Add `cache_control: {"type": "ephemeral"}` to system prompt + few-shot examples on stage1 + stage2 messages
- [ ] Verify `cache_read_input_tokens > 0` in the second response's `usage` field
- [ ] **Commit:** `Prompt caching on Haiku + Sonnet system prompts`

### T+24:30 → T+26:30 · Sonnet batching (~15 events/call)
- [ ] Refactor stage2 to batch 15 events per Sonnet call
- [ ] Update tool schema: tool input is `events: list[Event]`, output is `atoms: list[Atom]`
- [ ] Compare atom count + a manual quality skim of 10 atoms before vs after batching; if quality regresses, drop back to batch=5 or revert
- [ ] **Commit:** `Sonnet batching at 15 events/call`

### T+26:30 → T+28 · Idempotency cache wiring
- [ ] Write `ingest_cache` table on every stage1 + stage2 result
- [ ] Reruns of `contextlayer index` skip already-processed `source_id`s
- [ ] Verify by re-running on synthetic repo: second run should make ~0 API calls
- [ ] **Commit:** `Per-event idempotency cache`

### T+28 → T+30 · Hybrid retrieval (keyword + recency on top of cosine)
- [ ] Update `context_query`: top-20 by cosine → rerank with `score = 0.4*cosine + 0.4*keyword_overlap + 0.2*recency_boost` → top-k
- [ ] Keyword overlap = simple token-set Jaccard on lowercase nonstopword tokens
- [ ] Recency boost = normalize `created_at` against the repo's date range
- [ ] **Commit:** `Hybrid retrieval (cosine + keyword + recency)`

### T+30 → T+31 · `status` and `claude-md` polish
- [ ] `contextlayer status [--repo .]`: prints atom count, topic count, rule count, last indexed timestamp
- [ ] `contextlayer claude-md`: prints the CLAUDE.md snippet for users to append
- [ ] **Commit:** `CLI: status + claude-md subcommands`

### T+31 → T+33 · Full re-index + manual atom audit
- [ ] Run the full pipeline on the synthetic repo with all stages + caching + batching + idempotency
- [ ] Manually open each atom; spot-fix any with weak summaries (delete bad atoms manually in SQLite if needed, or revise the synthetic repo's PR text and re-index)
- [ ] Target: ≥40 atoms, ≥5 topics, ≥5 rules (success criterion §10)
- [ ] **Commit:** `Re-indexed synthetic repo, full quality pass`

### T+33 → T+35 · Demo question verify + commit demo script
**Decision pre-locked:** Q1 ("I need to add an endpoint that fetches a user's billing history") — see Resolved decisions at top of file.
- [ ] Run Q1 in both panes; verify all 4 expected atoms surface (`Result<T>`, async-first, SQLAlchemy session, don't share session)
- [ ] Quickly run Q2 and Q3 once each as confidence check; if Q2 or Q3 produces a more dramatic contrast than expected, swap (last-chance change)
- [ ] Write `docs/demo-script.md` with: question text, expected atom IDs, screenshot, timing notes
- [ ] If Claude Code doesn't reliably call `context_query`, strengthen `CLAUDE.md` nudge — never trust a flaky tool call on stage
- [ ] **Commit:** `Demo question verified + demo-script.md`

### 🚧 **G2 — STOP-AND-SHIP GATE @ T+35**
If any Phase 2B component (Opus, batching, hybrid retrieval) introduces a regression that wasn't there at T+14, OR any Phase 2A feature (note/explain/scan) doesn't smoke-test cleanly:
- Revert that component before moving on. Phase 2's job is to add quality + breadth, not to add risk.

---

## PHASE 3 — Demo materials (T+35 → T+42)

**Goal:** landing page live, 5-min demo video on the page, slide deck PDF ready, README polished. FastAPI stretch lands only if everything else is locked.

### T+35 → T+37 · Landing page
- [ ] `landing/index.html`: single static file, Tailwind CDN, Inter font
- [ ] Three sections: hero (problem + value prop + one-liner install), embedded MP4 (placeholder for now), waitlist (Tally embed)
- [ ] `landing/vercel.json` — minimal config
- [ ] `vercel --prod` → `contextlayer.vercel.app` live
- [ ] **Commit:** `Landing page v1 (Tailwind + Tally + Vercel)`

### T+37 → T+39 · Demo video record + edit
- [ ] Set up 2 Claude Code windows, both pre-warmed against the synthetic repo
- [ ] Record screencast (OBS preferred; QuickTime fallback). 1080p, 30fps.
- [ ] Run the locked demo script. Take 3 attempts; pick the best.
- [ ] Edit (iMovie / CapCut): title card "Same Claude Code. Same question. Watch the answer change.", subtle captions, side-by-side at 2:30, end card with landing page URL
- [ ] Export H.264 MP4 ≤30MB
- [ ] Drop into `landing/demo.mp4`, redeploy
- [ ] **Commit:** `Demo video recorded + landing page updated`

### T+39 → T+41 · Slide deck (now includes v1.1 roadmap slide referencing §5.7.4–5)
- [ ] 8–10 slides (Keynote / Pitch / Slides):
  1. Title
  2. Problem (10s read)
  3. Demo (embedded MP4 or static "watch the video" frame)
  4. Architecture (CLI + MCP + SQLite diagram from spec §4)
  5. Multi-agent pipeline (Haiku/Sonnet/Opus + extended thinking)
  6. Market (Cursor's $300M ARR; agent-tooling exits)
  7. Business model (Free → Pro $20 → Team $50 → Enterprise) — same row as Cursor, different layer
  8. GTM (HN → Anthropic Discord → bottom-up enterprise)
  9. Acquisition thesis (Anthropic, GitHub, Cursor, JetBrains, Vercel)
  10. Ask + contact
- [ ] Export PDF; check into `docs/pitch.pdf` (or link from README)
- [ ] **Commit:** `Pitch deck v1`

### T+41 → T+42 · FastAPI stretch (CONDITIONAL — adjustment #16; **first to cut if anything slips**)
**Gate:** only attempt if landing, video, deck are all locked AND demo runs clean.
- [ ] `git clone https://github.com/tiangolo/fastapi ~/clones/fastapi`
- [ ] `contextlayer index ~/clones/fastapi` — expected 5–8 min runtime
- [ ] Skim 20 atoms; assert they look meaningful
- [ ] If atoms are weak or pipeline times out, **cut the stretch — do not lose the synthetic demo**
- [ ] If atoms are strong, add a second `.mcp.json` and a second short demo segment ("and the same thing works on real OSS — here's FastAPI")
- [ ] **Commit (only if it works):** `FastAPI stretch: pre-indexed atoms`

### 🚧 **G3 — STOP-AND-SHIP GATE @ T+41**
If demo materials aren't done, FastAPI is cut without discussion. Submitting a polished synthetic-only demo beats a half-done FastAPI demo every time.

---

## PHASE 4 — Final dry runs + submit (T+42 → T+46)

### T+42 → T+44 · Dry runs (3 minimum, no exceptions)
- [ ] 3 consecutive end-to-end demo runs without intervention
- [ ] Time each run; target < 3 minutes
- [ ] Fix any demo-breaking bug immediately; do **not** add features
- [ ] If a run fails, restart the counter — need 3 consecutive cleans

### T+44 → T+45 · README + success criteria + clean-machine test
- [ ] Final README pass: 60s value prop, install one-liner (`uvx contextlayer index .`), demo GIF (3s of the video), architecture diagram (ASCII from spec §4), MIT license, BYOK note pointing at `console.anthropic.com`
- [ ] Walk every checkbox in spec §10 success criteria; tick them
- [ ] If a second machine is available: `uvx contextlayer index demo-data/acme-billing-api` on a clean clone, verify install path works (per spec checkbox)
- [ ] **Final commit:** `README + final polish for submission`

### T+45 → T+46 · Submit + 1h buffer
- [ ] Submit to hackathon portal with: GitHub URL, landing page URL, video URL, slide deck PDF, 1-paragraph blurb
- [ ] Tag the submission commit: `git tag -a hackathon-submission -m "Submitted to State of Oregon Claude Code Hackathon 2026-05-20"`
- [ ] 1h buffer for surprises
- [ ] Sleep. Be present at the demo.

### 🚧 **G4 — STOP-AND-SHIP GATE @ T+43**
If 3 consecutive clean dry runs aren't happening, freeze code at the last known-good commit (`git checkout <sha>`) and submit that. **Never demo unrehearsed code.**

---

## Risk register (per-phase)

| Phase | Risk | Mitigation |
|---|---|---|
| 1 | MCP SDK's API differs from what I remember | Spend 10 min reading the SDK README first; pin the version |
| 1 | Synthetic repo atoms come out generic | The generator is the leverage point — embed dramatic conventions explicitly, don't rely on Sonnet to discover them |
| 1 | Claude Code doesn't call `context_query` reliably | Strong `CLAUDE.md` nudge; if still flaky at T+13:30, manually prompt in the demo |
| 2 | Opus extended thinking blows past budget | `budget_tokens=8000` is a hard cap; fall back to Opus-without-thinking if needed |
| 2 | Sonnet batching breaks atom quality | Manual quality skim mandated between batched and unbatched runs |
| 2 | Caching doesn't engage (cache miss every time) | Verify in `usage` field; common cause is changing the system prompt between calls |
| 3 | Video recording fails mid-take | OBS + QuickTime both pre-configured; 3 takes minimum |
| 3 | Vercel deploy fails | Static HTML doesn't need Vercel; fall back to GitHub Pages on the repo |
| 3 | FastAPI atoms weak | **Cut.** Already optional per Appendix A #16 |
| 4 | Last-minute change breaks the demo | Tag a "demo-ready" commit at T+43 and only run from that tag on stage |
| 2A | New CLI subcommands (note/explain/scan) interact with existing atoms table | Always run pipeline smoke (the locked Q1 query) after each new CLI lands |
| 2A | scan emits low-quality atoms on weird repos | Keep code-scan events lightweight; let Haiku filter heavily |

---

## Always-shippable artifacts at each gate

| Gate | The submission if you stop here |
|---|---|
| G1 (T+14) ✅ DONE | Rough MVP video + GitHub repo with working `contextlayer index` / `mcp` on synthetic repo |
| G2 (T+35) | G1 + solo-dev features (note/explain/scan) + polished pipeline (Opus, caching, batching, hybrid retrieval) + locked demo question |
| G3 (T+41) | G2 + landing page + edited demo video + slide deck (with v1.1 roadmap slide) |
| G4 (T+43) | G3 + 3 clean dry runs + final README — the target submission |

---

## What's deliberately NOT in this plan

- `context_validate` (spec §5.7.4) — designed for v1.1; build risks the demo via false-positive tuning
- `contextlayer health` (spec §5.7.5) — designed for v1.1; the scorecard is the OSS-launch wedge
- Unit tests (per spec §10.5 — 3 smoke assertions only, manual e2e)
- CI / GitHub Actions (post-hackathon)
- Custom domain `contextlayer.dev` (post-hackathon, vercel.app subdomain is fine)
- Multi-user, auth, hosted tier, Slack/Linear adapters (all out of scope per spec §3)
- Premature optimization of retrieval (cosine + simple reranking is enough at 40–500 atoms)
- AST-based code analysis in `scan` (designed for v1.1; thin-slice file scan is enough for the demo)
- Pretty CLI animations beyond the progress line (judges don't grade ASCII art)

---

## Resolved decisions (closed 2026-05-18)

All five pre-T+0 decisions are resolved. See "Resolved decisions" block at the top of this file. Logged here for traceability:

1. ✅ **Sleep schedule** — operator-managed; hours below are productive hours
2. ✅ **Wall-clock T+0** — Mon 2026-05-18 evening (now)
3. ✅ **Demo question** — Q1 locked ("billing history endpoint"); verified at T+26-28
4. ✅ **Stage 3 Opus** — skipped in MVP, added in Phase 2 (preserves MVP-first guardrail)
5. ✅ **CLAUDE.md nudge** — start soft; strengthen at T+13:30 if Claude Code is flaky

---

## Verification before starting (per CLAUDE.md "Verify Plan")

Before T+0:
- [ ] `ANTHROPIC_API_KEY` exported (or in `.env`)
- [ ] `uv`, `gh`, `git` all working (verified earlier ✓)
- [ ] `~/.contextlayer/` writable
- [ ] Vercel account exists (or substitute GitHub Pages)
- [ ] OBS or QuickTime configured for screen recording
- [ ] Tally account exists (or substitute Formspree)
- [ ] Calendar blocked for the next 48h
- [ ] This plan reviewed and approved by operator

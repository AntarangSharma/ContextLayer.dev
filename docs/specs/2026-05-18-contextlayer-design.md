# ContextLayer.dev — Design Spec

**Date:** 2026-05-18
**Status:** Approved for implementation
**Author:** Antrang Sharma
**Target:** State of Oregon Claude Code Hackathon (online, 48h, demo Wed 2026-05-20 evening)
**Post-hackathon:** Startup trajectory toward $5M+ ARR in 18 months; acquisition-eligible

---

## 1. Executive summary

ContextLayer.dev is the missing context layer for AI coding agents. Every codebase has implicit context — why-this-not-that decisions, team conventions, deprecated paths, anti-patterns — that lives in PR comments, commit messages, and senior engineers' heads. Every AI agent (Claude Code, Cursor, Copilot, custom) rediscovers it badly every session. We index a repo's git + PR history with a multi-agent pipeline, extract structured "knowledge atoms," and serve them to any AI agent via MCP. Result: your Claude Code answers like a senior engineer who joined yesterday and read everything.

**Hackathon entry:** a working Python CLI + MCP server that demonstrates a dramatic before/after on a real OSS repo (FastAPI), plus a static landing page and a slide deck with a credible 18-month startup trajectory.

**Cost discipline:** $0 infra through deployment. Users bring their own Anthropic API key (BYOK). No paid services until investor funding.

---

## 2. Hackathon context

| Item | Value |
|---|---|
| Event | State of Oregon Claude Code Hackathon (sponsored by VIBES DIY, Anthropic API credits) |
| Track | Claude Code (engineers, frontier agents) |
| Format | Online, 48 hours |
| Demo deadline | Wednesday 2026-05-20 evening |
| Team | Solo |
| Judging weight | Technical ambition + execution (primary); business viability (investor judges in room) |
| Sponsor signal | Anthropic — MCP-native designs score highest |

**Strategic implication:** the design optimizes for "judge says 'this could be a real company'" rather than "judge says 'this is the most novel hack.'" Polish > novelty. Working MCP > fancy UI. Defensible business model > cute pitch.

---

## 3. Goals & non-goals

### In scope for hackathon (48h)

- CLI `contextlayer index <repo>` that ingests git log + PR data and produces an indexed knowledge store
- Multi-agent extraction pipeline (Haiku → Sonnet → Opus) with prompt caching, tool use, idempotency
- Local MCP server (stdio) exposing two tools to Claude Code: `context_query`, `context_list_topics`
- Pre-indexed demo on `tiangolo/fastapi` repository
- Synthetic backup repo (`acme-billing-api/`) as Plan B for demo
- Static landing page on Vercel (`contextlayer.vercel.app`) with waitlist
- 5-minute demo video + 8–10 slide pitch deck

### Explicitly out of scope (defer to post-hackathon)

- Slack ingestion (OAuth pain)
- Linear ingestion (OAuth pain)
- ADR file ingestion (low ROI for demo)
- Cursor / Cody / Aider MCP testing (Claude Code only)
- Web dashboard for browsing atoms (landing page only)
- Multi-user / auth (single user, local-only)
- Enterprise SSO (deck only, not built)
- Auto-update on git push (manual re-index only)
- Real-time updates (one-shot indexing only)
- Alternative embedding models (one model only)
- Custom domain `contextlayer.dev` (defer; use vercel.app subdomain)
- Hosted SaaS / managed indexing tier (post-investor)

---

## 4. Architecture

Two Python processes, one local SQLite store, two judge-visible artifacts (CLI + MCP server).

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI process (one-shot):  $ uvx contextlayer index <repo>        │
│                                                                  │
│   Ingestion adapters  →  Multi-agent extraction  →  SQLite (WAL) │
│   • git log (subprocess)    • Haiku  (relevance, batched ~100)   │
│   • gh CLI (PRs + comments) • Sonnet (extract,  batched ~15,     │
│   • repo file scan            tool use, prompt cache)            │
│                             • Opus   (dedup + structure, 1 call) │
└──────────────────────────────────────────────────────────────────┘
                                                          │
                                                          │ same DB file
                                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  MCP server (long-running stdio):  $ uvx contextlayer mcp        │
│                                                                  │
│   Tools exposed to Claude Code (and any other MCP client):       │
│   • context_query(question: str, k: int = 5) → list[Atom]        │
│   • context_list_topics() → list[Topic]                          │
│                                                                  │
│   Retrieval: hybrid (cosine over fastembed vectors +             │
│              keyword overlap + recency boost)                    │
└──────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ stdio
                                  │
                            Claude Code
```

**CLI shape:** single entrypoint `contextlayer` with subcommands:

| Subcommand | Purpose |
|---|---|
| `contextlayer index <repo>` | Run ingestion + extraction pipeline; write to `~/.contextlayer/<repo-hash>/index.db` |
| `contextlayer mcp [--repo <path>]` | Start the stdio MCP server against the indexed DB |
| `contextlayer status [--repo <path>]` | Show atom count, topic count, last index time (judge-friendly inspect) |
| `contextlayer claude-md` | Print the recommended CLAUDE.md snippet for users to append |

Dev invocation (during local development): `python -m contextlayer <subcommand>`. User invocation (production): `uvx contextlayer <subcommand>`. Both resolve to the same entrypoint.

### Why this shape

- **Two processes, one DB:** CLI writes infrequently and exits; MCP server runs while Claude Code is connected. SQLite in WAL mode handles concurrent read + occasional write without coordination.
- **Local-first:** Zero infrastructure to host, zero ports to expose, zero auth to build. Aligns with $0 cost ceiling and BYOK model.
- **MCP stdio over MCP HTTP:** Simplest transport, no networking, lowest demo risk. HTTP transport is a v2 concern when a hosted tier exists.
- **One SQLite file per repo:** copy-paste-able, demo-friendly, the MCP server can be pointed at it with one flag.

---

## 5. Components

### 5.1 Ingestion adapters

Three small modules under `contextlayer/ingest/`:

| Adapter | Source | Implementation |
|---|---|---|
| `git_log.py` | All commits on default branch | `git log --format=...` via subprocess; parse author, date, subject, body, files changed |
| `gh_prs.py` | All merged PRs + their review comments | `gh pr list --state merged --json ...` + `gh pr view <n> --json comments`; cache responses |

(ADR file ingestion is deferred to Appendix B post-hackathon roadmap.)

Output: a stream of `RawEvent` records with a uniform shape (`source_type`, `source_id`, `timestamp`, `text`, `metadata`). Idempotent — re-runs use a cache keyed by `source_id`.

### 5.2 Multi-agent extraction pipeline

The technical-ambition centerpiece. Three stages, each with the cheapest model that does the job well.

#### Stage 1 — Haiku (relevance filter)

- **Input:** raw events, batched ~100 per call
- **Prompt:** system prompt cached via `cache_control`; asks "for each event, does it contain a team convention, design decision, deprecation, or anti-pattern?"
- **Output:** structured array of `{event_id, keep: bool, category: str}`
- **Volume:** typical mid-size repo = 5–10k events; Haiku discards ~85–90%
- **Cost:** ~$0.05–0.15/repo with caching

#### Stage 2 — Sonnet (atom extractor)

- **Input:** events that survived Stage 1, batched ~15 per call
- **Mechanism:** Anthropic **tool use** with a strict JSON schema enforces atom shape; zero parse failures
- **Prompt:** system prompt + few-shot examples cached via `cache_control`
- **Output:** array of `Atom` objects (see schema below)
- **Volume:** ~500–800 events surviving filter → ~30–50 Sonnet calls
- **Cost:** ~$0.20–0.40/repo with caching + batching

#### Stage 3 — Opus (global structurer, **with extended thinking enabled**)

- **Input:** the full set of extracted atoms (typically 300–500)
- **Single call:** Opus reads the entire set in one shot with **`thinking: {type: "enabled", budget_tokens: 8000}`**
- **Why extended thinking:** dedup + conflict resolution + topic clustering is reasoning over the whole set — exactly the task extended thinking is designed for. Costs ~+$0.50 in thinking tokens but meaningfully improves edge-case handling (conflicting atoms, ambiguous topic boundaries).
- **Responsibilities:**
  1. Deduplicate near-duplicate atoms (same rule discovered in two PRs)
  2. Resolve conflicts (newer atom wins; older linked as evidence)
  3. Group atoms into named topics ("API design", "auth", "testing", etc.)
  4. Promote high-confidence atoms (≥0.8) to a "rules" surface (always-on context for the agent)
- **Cost:** ~$0.80–1.00/repo (with extended thinking)

#### Pipeline cost & wall-time

- **Total API cost per repo indexed:** ~$1.05–$1.55 (Haiku ~$0.15 + Sonnet ~$0.30 + Opus w/ extended thinking ~$1.00). Still ~2× cheaper than the unoptimized v0.
- **Total wall time:** 3–8 minutes for a mid-size repo
- **Resumability:** per-event idempotency cache; if any stage fails mid-run, re-running skips already-processed events

#### Judge-defensible answer

> *"We split across three models for cost-quality fit, not for show. Haiku is 90% of the volume because relevance filtering is a small-model task. Sonnet does the atom extraction where structure quality matters, with tool-use enforcing the JSON schema so we never have parse failures. Opus runs once at the end with extended thinking enabled because dedup, conflict resolution, and topic grouping is reasoning over the whole atom set. With prompt caching, Sonnet batching, and per-event idempotency, marginal cost per repo indexed is ~$1.50 — and we have a clean path to halve that in v2 by moving the Haiku stage to the Batches API."*

### 5.3 Atom schema

```jsonc
{
  "id": "a_47fc",                              // hash of summary + source_refs
  "category": "convention | decision | deprecation | anti-pattern",
  "summary": "Use Result<T> for domain errors, not exceptions",
  "rationale": "PR #421 — exceptions broke async tracing in Q3 incident",
  "scope": "src/api/**",                       // glob, or null for repo-wide
  "source_refs": ["pr:421", "commit:abc123"],  // for citation in MCP responses
  "confidence": 0.87,                          // Sonnet-assigned, validated by Opus
  "created_at": "2026-05-18T..."
}
```

Embeddings stored separately (see Storage).

### 5.4 Storage

**Location:** `~/.contextlayer/<repo-hash>/index.db`. Repo hash = SHA1 of the git remote URL (if present) or the absolute repo path (fallback). Same repo cloned to different paths shares an index.

**Schema:**

```sql
PRAGMA journal_mode = WAL;

CREATE TABLE atoms (
  id           TEXT PRIMARY KEY,
  category     TEXT NOT NULL,
  summary      TEXT NOT NULL,
  rationale    TEXT,
  scope        TEXT,
  source_refs  TEXT NOT NULL,    -- JSON array
  confidence   REAL NOT NULL,
  is_rule      INTEGER DEFAULT 0,
  created_at   TEXT NOT NULL
);

CREATE TABLE atom_embeddings (
  atom_id      TEXT PRIMARY KEY REFERENCES atoms(id) ON DELETE CASCADE,
  vector       BLOB NOT NULL    -- 384-d float32, packed
);

CREATE TABLE topics (
  id           TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  summary      TEXT,
  atom_ids     TEXT NOT NULL    -- JSON array
);

CREATE TABLE ingest_cache (
  source_id    TEXT PRIMARY KEY,
  source_type  TEXT NOT NULL,
  stage1_result TEXT,           -- Haiku output, JSON
  stage2_result TEXT,           -- Sonnet output, JSON (null if filtered out at stage 1)
  processed_at TEXT NOT NULL
);
```

**Embeddings:**

- Model: `BAAI/bge-small-en-v1.5` via **`fastembed`** library (ONNX runtime; ~100MB install footprint vs `sentence-transformers`' ~2GB with PyTorch)
- Dimensions: 384, packed as `float32` BLOB
- Search: brute-force cosine in numpy (`np.dot(matrix, query) / norms`) — microseconds at ~500 atoms, no vector DB extension needed

**Why no `sqlite-vec`:** at our scale, brute-force cosine is faster than the round-trip to the extension, and `sqlite-vec` breaks on Python installs we can't control (judge laptops, CI). Drop the dependency.

### 5.5 MCP server

`contextlayer/mcp/server.py` — stdio transport, two tools.

```python
@server.tool()
async def context_query(question: str, k: int = 5) -> list[Atom]:
    """Search team conventions, decisions, and anti-patterns extracted
    from this repo's history. Call this BEFORE proposing code changes
    or design choices in this codebase."""

@server.tool()
async def context_list_topics() -> list[Topic]:
    """List discovered knowledge topics in this codebase."""
```

**Retrieval (`context_query`):**
1. Embed the question with the same fastembed model
2. Cosine over all atom vectors → top-20
3. Re-rank by: keyword overlap (0.4×) + recency boost (0.2×) + base cosine (0.4×)
4. Return top-k with full atom payload + source refs

**Claude Code wiring** — judges add one block to `.mcp.json` at repo root:

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "uvx",
      "args": ["contextlayer", "mcp", "--repo", "."]
    }
  }
}
```

**Bundled `CLAUDE.md` snippet** — ships with the CLI; users append it to their repo's CLAUDE.md to turn the MCP from passive to active:

> *"Before proposing code changes in this repo, call `context_query` with what you intend to do. The repo has codified team conventions and prior decisions; respect them."*

**DB path resolution.** The MCP server takes `--repo <path>` (default `.`) and resolves the SQLite location using the same hash function as the indexer (SHA1 of the git remote URL with absolute-path fallback — see §5.4). If no index exists for the repo, the server returns an empty result with an explanatory message rather than failing.

### 5.6 Secrets & API key handling

- Anthropic API key loaded exclusively from `ANTHROPIC_API_KEY` env var
- Never written to disk, never logged, never included in atom payloads
- README documents the BYOK requirement and points users to `console.anthropic.com` for keys
- No support for `.env` files in v1 — users export the var in their shell (standard pattern, zero failure modes)
- If the env var is missing at index time, the CLI exits with a clear message; MCP server runs fine without it (no Anthropic calls happen during serving)

---

## 6. Distribution & deployment

### 6.1 Code repository

- Public GitHub repo: [github.com/AntarangSharma/ContextLayer.dev](https://github.com/AntarangSharma/ContextLayer.dev)
- MIT license — strategic: community moat, contribution surface, stronger acquisition story
- README with: 60-second value prop, install one-liner, demo GIF, architecture diagram, link to landing page

### 6.2 Install path

Primary: `uvx contextlayer index .` — zero install, no virtualenv, no Python version issues. Modern Python distribution via `uv`/PyPI.

Fallback: `pip install contextlayer` for users who don't have `uv` yet.

### 6.3 Landing page

- Single static `index.html` + Tailwind CDN
- Deployed to Vercel, free Hobby tier, auto-deploys from GitHub `main`
- URL: `contextlayer.vercel.app` (custom domain deferred)
- Three blocks: hero (problem + value prop), embedded demo MP4 (self-hosted on Vercel, not Loom), waitlist via Tally
- Engineering time: 2–3 hours

### 6.4 Deployment cost timeline

| Phase | Duration | Cost to me |
|---|---|---|
| Build + hackathon | 48h | $0 (hackathon Anthropic credits) |
| Launch + BYOK users | 0–6 months | $0 (users bring their own Anthropic key) |
| Post-investor | 6mo+ | Variable (managed tier, paid infra) |

---

## 7. Business model (for the deck)

| Tier | Price | Includes | Comparable |
|---|---|---|---|
| **Free / OSS** | $0 + your own API key | Self-host, MCP server, all ingestion adapters | — |
| **Pro** | $20/seat/mo | Hosted indexing, multi-repo, Slack/Linear adapters | Cursor Pro $20, Copilot Pro $19 |
| **Team** | $50/seat/mo | + team-wide knowledge sharing, admin, audit basics | Glean $40–100/seat/mo |
| **Enterprise** | $50K–500K/yr | SSO, on-prem, custom ingestion, SLA | Sourcegraph, Glean enterprise |

**Positioning:** "Same price as Cursor, different layer. Cursor is the IDE; ContextLayer is the context bus every AI agent on your repo plugs into — Claude Code, Cursor, Copilot, custom internal agents."

**GTM (first 90 days):**

1. HN launch: "Show HN: the missing context layer for Claude Code"
2. Anthropic Discord + Claude Code community — frictionless drop-in MCP
3. Bottom-up enterprise: devs adopt free tier → team upgrade → CTO buys SSO (same path as Linear, Vercel, Cursor)

**Acquisition thesis:** Anthropic, GitHub, Cursor, JetBrains, or Vercel each have a strategic reason to own this layer. Acquihire range at $5M+ ARR is $50M–$500M based on comparable agent-tooling exits.

---

## 8. Demo plan

**Primary demo repo:** `tiangolo/fastapi`. Reasons: rich PR discussion, audience knows it instantly, I can verify atom accuracy because I know FastAPI, strong debate-worthy conventions (async vs sync, dependency injection, exception handling) for clean before/after contrast.

**Backup repo:** `acme-billing-api/` — 15-PR synthetic repo I author during prep with deliberately embedded conventions (Result type adopted in PR #3, legacy helper deprecated in PR #8, async-first decision in PR #11). Bulletproof but obviously curated.

**Both pre-indexed.** Index DB committed to a `demo-data/` folder in the repo so judges can reproduce locally.

**Three candidate demo questions** (A/B'd in prep, lock the strongest before submission):

1. "I need to add an endpoint that fetches a user's billing history — show me how."
2. "Should this endpoint be async or sync?"
3. "How should I inject the database session into this route?"

**3-minute demo flow:**

| t | Action |
|---|---|
| 0:00 | Title card: "Same Claude Code. Same question. Watch the answer change." |
| 0:10 | **Pane A** (no MCP): ask the locked demo question → generic, plausible, wrong-shape answer |
| 0:35 | Cut to terminal: `contextlayer index .` runs as visual theatre (small subset, ~30s). Show pipeline progress: `Haiku filtered 4,832 → 487 events · Sonnet extracted 312 atoms · Opus organized into 14 topics` |
| 1:35 | Show `.mcp.json` snippet on screen — "one block, that's the install" |
| 1:50 | **Pane B** (MCP pre-loaded against the full pre-indexed DB): ask the **exact same question** → Claude Code calls `context_query` → answer cites atoms (`Result<T>`, scoped auth middleware, deprecated helper, PR #421) |
| 2:30 | Split-screen the two answers side-by-side |
| 2:45 | Cut to landing page + business model slide |

**The two-pane setup eliminates the single highest-risk step** (restarting Claude Code mid-demo and waiting for MCP to reconnect).

---

## 9. Risk register

Ordered by likelihood × impact, with mitigations baked into the design.

| # | Risk | Mitigation |
|---|---|---|
| 1 | MCP server fails to connect during live demo | Two pre-warmed Claude Code panes; never restart on stage |
| 2 | Sonnet returns malformed atom JSON mid-run | Anthropic tool use with strict JSON schema; zero free-form JSON parsing |
| 3 | Pre-indexed FastAPI atoms are weak / low contrast | Three demo questions A/B-tested in prep; synthetic backup repo as Plan B |
| 4 | Multi-agent pipeline overruns time budget | Sonnet batching is the only novel engineering; if it slips, fall back to one-event-per-call (works, just slower/pricier) |
| 5 | Anthropic API outage during demo | Pre-indexed DB is local; the after-demo doesn't touch the API. Drop the live re-index theatre if network is down |
| 6 | `gh CLI` not authenticated on a fresh judge clone | README documents `gh auth login`; pre-indexed DB ships with the demo so judges don't need to re-index to see results |
| 7 | `fastembed` model download blocks first run | Pre-warm during install; document expected 30s first-run download |
| 8 | Time overrun on landing page polish | Locked to single static HTML; resist any framework temptation |

---

## 10. Success criteria

Binary self-assessment for Wednesday morning:

- [ ] Pre-indexed FastAPI repo, ≥100 atoms across ≥10 topics, browsable via MCP from Claude Code
- [ ] Three demo questions tested; strongest one locked
- [ ] Before/after demo runs end-to-end in <3 minutes with no restart
- [ ] Synthetic backup repo (`acme-billing-api/`) ready as Plan B
- [ ] Landing page live at `contextlayer.vercel.app`, waitlist form functional
- [ ] 5-minute demo video recorded, edited, captioned
- [ ] Slide deck (8–10 slides): problem → demo → market → model → roadmap → team → ask
- [ ] Public GitHub repo with clean README, architecture diagram, install one-liner, MIT license
- [ ] BYOK config documented in README — users add their own `ANTHROPIC_API_KEY`
- [ ] `uvx contextlayer` install path tested end-to-end on a clean machine

### 10.5 Testing strategy

- **Manual end-to-end test** against the synthetic backup repo (`acme-billing-api/`) before submission: index → start MCP → connect Claude Code → ask known question → assert atom IDs in the response
- **3 pipeline smoke assertions** (lightweight, in `tests/smoke/`):
  1. Sonnet tool-use call returns a valid atom (schema validation)
  2. Hybrid retrieval returns at least 1 result for a known-good question
  3. MCP server starts and exposes both tools (capability negotiation)
- **No automated test suite** for hackathon scope (no unit tests, no CI). Add `pytest` + GitHub Actions in v2.
- **API outage rehearsal**: pull network during a dry run, verify the post-indexing demo flow still works against the local DB

---

## 11. Open questions

None. All design decisions are locked. Implementation can proceed.

---

## Appendix A — Design decisions log (12 hardenings applied)

For traceability between sections and stress-test improvements:

| # | Section | Decision | Why |
|---|---|---|---|
| 1 | 5.4 | Drop `sqlite-vec`, use numpy brute-force cosine | Eliminates a C-extension install footgun; faster at our scale |
| 2 | 5.4 | `PRAGMA journal_mode=WAL` | Eliminates CLI-write vs MCP-read lock edge case |
| 3 | 5.4 | Repo hash = SHA1(git remote URL) with path fallback | Same repo across paths shares index |
| 4 | 5.4 | Swap `sentence-transformers` → `fastembed` | ~10× smaller install, 3× faster cold-start, same embedding quality |
| 5 | 5.2 | Sonnet batched to ~15 events/call | ~10× API cost reduction, faster wall time |
| 6 | 5.2 | Haiku batched to ~100 events/call | Fewer round-trips |
| 7 | 5.2 | Prompt caching on Haiku + Sonnet system prompts | ~80% cost reduction on cached tokens, ~75% latency reduction |
| 8 | 5.2 | Anthropic tool use for Sonnet atom extraction | Schema-enforced output, zero parse failures |
| 9 | 5.2 | Per-event idempotency cache (`ingest_cache` table) | Resumable runs after transient failures |
| 10 | 8 | Two pre-warmed Claude Code panes, no restart on stage | Removes the single highest-risk demo step |
| 11 | 6.3 | Self-host demo MP4 on Vercel (not Loom) | One fewer external dependency, faster page load |
| 12 | 7 | BYOK (users bring their own Anthropic API key) | $0 API cost to me through deployment, standard OSS pattern |
| 13 | 5.2 | Extended thinking on Opus global structurer | Reasoning-heavy task; meaningfully better dedup/topic grouping for ~+$0.50/run |
| 14 | 5.6 | Explicit `ANTHROPIC_API_KEY` env var; never disk/logs | Standard secrets pattern, judge-defensible |
| 15 | 10.5 | Manual e2e + 3 pipeline smoke assertions, no full test suite | Right scope discipline for 48h hackathon |

---

## Appendix B — Out-of-scope work (post-hackathon roadmap)

Ordered by likely sequencing:

1. **Polish the OSS release** — better install UX, error messages, docs
2. **Anthropic Batches API for Haiku stage** — 50% additional cost reduction on bulk indexing (24h latency acceptable in batch mode)
3. **Optional anonymous telemetry** — privacy-respecting, opt-in; counts of indexes/queries to understand adoption
4. **Slack ingestion adapter** — OAuth + Slack export parsing
5. **Linear ingestion adapter** — OAuth + Linear API
6. **ADR file ingestion** — markdown walker for `**/{ADR,decisions,architecture}*.md`
7. **Cursor / Cody / Aider MCP testing** — verify cross-agent compatibility
8. **Hosted SaaS tier** — managed indexing, multi-tenant SQLite or Turso
9. **Team-wide knowledge sharing** — shared index across team members
10. **Auth + multi-user** — Clerk or Supabase Auth
11. **Enterprise SSO** — Workos
12. **On-prem deployment** — Docker image, install docs
13. **Documentation site** — Docusaurus or GitBook (free), once tool has >100 users
14. **Custom ingestion adapters** — SDK for enterprises with bespoke sources
15. **Real-time updates** — auto-reindex on git push (GitHub Action or local hook)
16. **Automated test suite + CI** — pytest + GitHub Actions, with fixtures for the synthetic backup repo

# ContextLayer.dev — Design Spec

**Date:** 2026-05-18
**Status:** Approved for implementation
**Author:** Antrang Sharma
**Target:** State of Oregon Claude Code Hackathon (online, 48h, demo Wed 2026-05-20 evening)
**Post-hackathon:** Startup trajectory toward $5M+ ARR in 18 months; acquisition-eligible

---

## 1. Executive summary

ContextLayer.dev is the missing context layer for AI coding agents. Every codebase has implicit context — why-this-not-that decisions, team conventions, deprecated paths, anti-patterns — that lives in PR comments, commit messages, code structure, and senior engineers' heads. Every AI agent (Claude Code, Cursor, Copilot, custom) rediscovers it badly every session. We index a repo from **three sources** — git + PR history, the live code structure, and user-authored "decision journal" notes — with a multi-agent pipeline, extract structured "knowledge atoms," and serve them to any AI agent via MCP. Solo devs without rich PR history get value on day one because code-aware extraction and the decision-journal CLI work on any repo. Result: your Claude Code answers like a senior engineer who joined yesterday and read everything — including the unwritten parts.

**The moat (v2 + v3, designed in §5.8).** The features above are productivity wins. The defensible business is the *immune system*: continuous Convention Drift Detection (alert when 34% of new code quietly violates a convention), the Failure Loop (incident → automatically extracted "never do this again" atom → all future AI sessions warned), and Cross-Repo Intelligence (anonymized network effects: *"78% of teams at your scale regret not adding connection pooling before 50k DAU — you don't have it"*). These are not productivity arguments. They are business-continuity arguments. That is what unlocks enterprise budget and what no CLAUDE.md, no Cursor rule, and no manual process can replicate.

**Hackathon entry:** a working Python CLI + MCP server that demonstrates a dramatic before/after on a deterministic 15-PR demo repo (`acme-billing-api/`) authored during prep — synthetic but bulletproof, with guaranteed dramatic atoms. A `tiangolo/fastapi` showcase is staged as an optional "wow if time" stretch, not a critical-path dependency. Plus a static landing page and a slide deck with a credible 18-month startup trajectory.

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

**Core (Phase 1 — COMPLETE):**
- CLI `contextlayer index <repo>` that ingests git log + PR data and produces an indexed knowledge store
- Multi-agent extraction pipeline (Haiku → Sonnet → Opus) with prompt caching, tool use, idempotency
- Local MCP server (stdio) exposing two tools to Claude Code: `context_query`, `context_list_topics`

**Solo-dev features (Phase 2 — adds "works on any repo, day one"):**
- `contextlayer scan <repo>` — code-aware ingestion adapter (thin slice: manifests, README, top-N source files via Haiku heuristics) so the pipeline produces atoms even when PR history is sparse
- `contextlayer note "<decision>"` — Decision Journal CLI; writes user-authored atoms directly to the DB without invoking the multi-agent pipeline
- `contextlayer explain` — Onboarding Doc generator; produces a polished markdown brief from indexed atoms (stack, top conventions, decisions, anti-patterns)

**Demo + distribution (Phase 3):**
- Pre-indexed demo on synthetic `acme-billing-api/` repo (15 PRs, hand-authored conventions; deterministic and bulletproof) — **primary demo path**
- Optional pre-indexed demo on `tiangolo/fastapi` as a "wow if time" stretch goal — **not on the critical path**
- Static landing page on Vercel (`contextlayer.vercel.app`) with waitlist
- 5-minute demo video + 8–10 slide pitch deck

### Stretch (v1.1, post-hackathon — designed but not built for the demo)

These two features are designed below in §5.7.4–5.7.5 because they're load-bearing for the OSS launch narrative and judges WILL ask about them. They are not on the 48h critical path.

- **Real-time anti-pattern detection** — new MCP tool `context_validate(code, file_path)` that AI agents call before finalizing a response; returns matching anti-pattern atoms. Designed; ships in v1.1.
- **Repo Health Score** — `contextlayer health` CLI; consistency score, knowledge gaps, drift detection. Designed; ships in v1.1.

### Explicitly out of scope (defer to v1.2+)

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

| Subcommand | Phase | Purpose |
|---|---|---|
| `contextlayer index <repo>` | 1 (done) | Run git + PR ingestion + extraction pipeline; write atoms to `~/.contextlayer/<repo-hash>/index.db` |
| `contextlayer mcp [--repo <path>]` | 1 (done) | Start the stdio MCP server against the indexed DB |
| `contextlayer status [--repo <path>]` | 1 (done) | Show atom count, topic count, last index time (judge-friendly inspect) |
| `contextlayer claude-md` | 1 (done) | Print the recommended CLAUDE.md snippet for users to append |
| `contextlayer scan <repo>` | **2** | Code-aware ingestion: scan manifests + README + top source files; feed events into the same pipeline. Unlocks day-one value for repos with sparse/zero PR history |
| `contextlayer note "<decision>" [--rationale "<why>"] [--scope "<glob>"]` | **2** | Decision Journal: write a user-authored atom directly to the DB. Bypasses the multi-agent pipeline. Costs $0, takes milliseconds |
| `contextlayer explain [--out FILE]` | **2** | Onboarding Doc generator: render the indexed atoms as a polished markdown brief (stack, conventions, decisions, anti-patterns). Designed to replace the "let me explain my project" tax every session |
| `contextlayer validate <file>` | v1.1 | Real-time anti-pattern check on a code snippet/file (also exposed as MCP tool `context_validate`) |
| `contextlayer health` | v1.1 | Repo Health Score: consistency, knowledge gaps, drift detection — standalone value-add even before MCP integration |

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

**Server scaffold.** Built on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) (`pip install mcp`). We do not roll stdio framing, JSON-RPC message handling, or capability negotiation from scratch — the SDK handles transport, message routing, and tool registration. Our code stays focused on the two tool implementations and the retrieval logic. This both reduces implementation risk in the 48h window and lets us point judges at "we're built on Anthropic's MCP SDK" as a credibility signal.

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

### 5.7 Solo-dev features (any repo, day one)

The original design assumes a repo with rich PR history. That's enterprise-flavoured — most solo devs and small teams don't have that data. The five features below extend ContextLayer to deliver value on *any* repo, even one created an hour ago, even one with zero PRs.

**Why this matters strategically:** without these features, the addressable market is "engineering teams with mature PR cultures" — maybe 10% of GitHub. With them, it's "anyone with a Git repo and Claude Code installed" — 10× larger TAM and a 10× simpler GTM ("works on YOUR repo, today, free").

**Phase markers:** §5.7.1, §5.7.2, §5.7.3 are Phase 2 (hackathon scope). §5.7.4 and §5.7.5 are designed below but ship in v1.1 to protect the demo timeline.

#### 5.7.1 Code-aware ingestion (`contextlayer scan`) — Phase 2

**Problem solved:** new repos, solo OSS projects, and small teams often have zero useful PR history. The multi-agent pipeline starves. Solution: read the *code itself* as a source of conventions.

**What it scans (thin slice for v1):**

| Source | What we extract |
|---|---|
| `pyproject.toml` / `package.json` / `Cargo.toml` / `go.mod` | Stack identification, dependency choices, version pinning style |
| `README.md` / `CONTRIBUTING.md` / top-level `*.md` | Project intent, stated conventions, getting-started steps |
| File-extension distribution (counts per `.ts`/`.py`/`.rs`/etc.) | Inferred primary language(s), build system signals |
| Top-N largest source files (by line count, capped at 20 files) | Sonnet reads each and extracts: error-handling style, naming conventions, module boundaries, observed patterns |

**How it feeds the pipeline:** the scanner emits `RawEvent` records with `source_type="code_scan"`. They flow into the *same* Haiku → Sonnet → Opus pipeline as git/PR events. No new pipeline, no new storage. Atoms produced have `source_refs` like `["file:pyproject.toml"]` or `["file:src/api/users.py"]`.

**What v1.1 adds:** AST-based extraction for higher-fidelity conventions (function naming patterns, decorator usage, exception-vs-Result style detection). Out of scope for hackathon.

**Cost impact:** scanning adds ~$0.10–0.30 per repo (10–30 small Sonnet calls on individual source files). Total per-repo cost rises from ~$1.50 to ~$1.80.

**Usage:**

```bash
# Standalone — produce atoms purely from code:
$ contextlayer scan .

# Or combined with git/PR (recommended):
$ contextlayer index .          # adds code_scan events to the pipeline run
```

`index` invokes `scan` as one of its ingestion adapters when run with no flags. `scan` alone exists as a fast path for "I just want atoms from code, skip the gh CLI dance."

#### 5.7.2 Decision Journal (`contextlayer note`) — Phase 2

**Problem solved:** solo devs don't write PR descriptions. They make decisions in their head, in chat with themselves, while coding. Those decisions evaporate. By the next session, even *they* forget the why.

**Design:** a one-line CLI that captures a decision as a knowledge atom directly — no multi-agent pipeline, no Anthropic call, no cost. It's a structured commit message for thoughts that don't warrant a commit.

```bash
$ contextlayer note "switched from axios to fetch — bundle size win, no other deps needed"
$ contextlayer note "all timestamps are UTC; never localize at the storage layer" --scope "src/**"
$ contextlayer note "auth tokens expire in 7d; do not make this per-route" \
    --rationale "PR review with security team 2026-05-15"
```

**Atom shape:** identical to a pipeline-extracted atom but with `category="user_decision"`, `source_refs=["note:<timestamp>"]`, `confidence=1.0` (user-stated, no inference). The note is added to the atoms table immediately; the next `context_query` from any MCP client surfaces it.

**Implementation cost:** ~1–2 hours. Atoms table already exists. New `note` subcommand inserts a row with `source_type="note"` and the current `cwd` as scope hint. Embeddings computed locally via the same fastembed pipeline.

**Demo angle:** drop one beat into the rehearsal — *"now I'm coding, I make a decision, I capture it in one line. The next AI session knows it forever."* Optional, doesn't require restructuring the locked 3-min demo.

#### 5.7.3 Onboarding Doc Generator (`contextlayer explain`) — Phase 2

**Problem solved:** every Claude Code session, every new collaborator, every future-self starts with the "let me explain my project from scratch" tax. This is the single most repeated piece of friction in AI-assisted development.

**Design:** a CLI that reads the indexed atoms and renders a polished, single-file markdown brief. Designed to be the artifact a user drops into a new chat (or appends to `CLAUDE.md`) and gets instant context.

```bash
$ contextlayer explain
# Writes to stdout (default) — pipe to a file or clipboard

$ contextlayer explain --out PROJECT_BRIEF.md
# Writes to file
```

**Output structure (template lives in `contextlayer/templates/explain.md.j2`):**

```markdown
# Project: <repo-name>

## Stack (inferred)
- Language: Python 3.11+
- Web framework: FastAPI
- Database: SQLite + Postgres (per pyproject.toml)
- Tests: pytest

## Top conventions
1. Use Result<T> for domain errors, not exceptions (PR #421)
2. All timestamps stored as UTC at the data layer
3. Async endpoints by default; sync only for CPU-bound work
...

## Active decisions (recent)
- 2026-05-15 · Auth tokens 7d expiry, not per-route configurable
- 2026-05-10 · Switched from axios to fetch (note)
...

## Anti-patterns to avoid
- Don't import from `legacy_billing.py` — deprecated PR #487
...

## Topic index
- API design (12 atoms) · Auth (7) · Testing (9) · ...
```

**How it works:** queries the indexed atom store, groups by `category` and `topic`, sorts by `confidence` desc and `created_at` desc, renders via a Jinja2 template. ~2–3 hours of implementation.

**Demo angle:** an artifact judges can hold in their hands ("here's a complete project brief, generated from your repo in seconds"). Strong companion to the MCP before/after demo. Mention briefly in the closing 15 seconds of the demo if it's ready.

#### 5.7.4 Real-time anti-pattern detection (`context_validate`) — v1.1

**Problem solved:** `context_query` is pull-based — the agent has to remember to ask. Anti-patterns matter most when the agent is about to ship code that violates them, and a passive retrieval pattern misses these moments.

**Design:** a third MCP tool that the agent calls *after* drafting code but *before* finalizing the response. Returns matching anti-pattern atoms with a severity score so the agent can self-correct.

```python
@server.tool()
async def context_validate(code: str, file_path: str | None = None) -> ValidationResult:
    """Check a code snippet against known anti-patterns and conventions.
    Call this AFTER drafting code, BEFORE finalizing your response."""
```

**Implementation sketch:**

1. Embed the snippet with the same fastembed model
2. Cosine over atoms where `category in ("anti-pattern", "deprecation")` → top-20
3. For each candidate, run a small Sonnet "does this code actually violate this rule?" call (batched, 5 candidates per call) → returns yes/no + severity
4. Return matched violations with the source atom and a suggested fix

**Why v1.1 not v1:** the design is clean but the validation prompt needs tuning to avoid false positives (which destroy trust). That tuning takes a day of careful work — not worth risking the hackathon demo for it. Ships at OSS launch (3 weeks post-hackathon) with public tuning data.

**Bundled CLAUDE.md update (v1.1):** the recommended snippet grows from one line to two — *"call `context_query` before drafting, and `context_validate` after."*

#### 5.7.5 Repo Health Score (`contextlayer health`) — v1.1 (designed below; ships at OSS launch)

**Problem solved:** users want a reason to run ContextLayer *before* they trust it enough to wire it into Claude Code. A standalone score gives instant, shareable value — and is a perfect blog-post / Show HN hook.

**Design:** a CLI that runs over the indexed atoms + raw file scan results and emits three numbers plus a one-page report.

```bash
$ contextlayer health
✓ Indexed 234 atoms · 18 topics · last scan 2 minutes ago

Repo Health Score:  73 / 100

  Consistency:    82 / 100   (error handling, naming, module structure)
  Coverage:       64 / 100   (% of modules with documented rationale)
  Drift:          71 / 100   (files contradicting established patterns)

Top knowledge gaps:
  • src/billing/ has 12 modules, 0 documented decisions
  • Recent commit a3f1c2 contradicts the Result<T> convention (PR #421)
```

**Scoring (v1.1 sketch):**

| Sub-score | Computation |
|---|---|
| Consistency | For each detected convention, % of relevant files that follow it. Aggregate weighted by file size. |
| Coverage | % of source files that have at least one atom whose `scope` matches their path. |
| Drift | Run anti-pattern detection (§5.7.4) over recent commits; count violations weighted by file recency. |

**Why standalone-valuable:** people will run it just for the score. Then they stay for the MCP integration. Same playbook as Lighthouse for web perf — the score is the wedge.

**Distribution surface:** also produces a shareable badge SVG (`![Repo Health: 73](contextlayer.dev/badge/...)`) and a public scorecard page (post-hosted-tier). For v1.1: just the CLI output and a JSON dump.

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

**Primary demo repo:** `acme-billing-api/` — a 15-PR synthetic repo authored during prep with deliberately embedded conventions (`Result<T>` type adopted in PR #3, legacy `db_helper` deprecated in PR #8, async-first decision in PR #11, etc.). Deterministic, bulletproof, guaranteed dramatic atoms. Yes, it's curated — and that's the point: every atom is verifiable against the source PR, the before/after contrast is engineered to be unambiguous on stage, and re-indexing during the demo finishes in under a minute on any laptop.

**Optional stretch repo:** `tiangolo/fastapi`. If time permits inside the polish window (post-MVP), swap the demo to a real OSS repo for additional credibility ("works on production code, not just our toy"). Rich PR discussion, audience knows it instantly, strong debate-worthy conventions (async vs sync, dependency injection, exception handling). **Not on the critical path** — do not let this slip the demo.

**Pre-indexing.** The synthetic repo's index DB is committed to a `demo-data/` folder so judges can reproduce locally. FastAPI's index DB is added to `demo-data/` only if the stretch goal lands.

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
| 3 | Synthetic primary repo atoms read as weak / low-contrast | Conventions engineered for contrast at authoring time; three demo questions A/B-tested before lock; FastAPI is an optional credibility upgrade, **not** a fallback (the synthetic repo IS the bulletproof path) |
| 4 | Multi-agent pipeline overruns time budget | Sonnet batching is the only novel engineering; if it slips, fall back to one-event-per-call (works, just slower/pricier) |
| 5 | Anthropic API outage during demo | Pre-indexed DB is local; the after-demo doesn't touch the API. Drop the live re-index theatre if network is down |
| 6 | `gh CLI` not authenticated on a fresh judge clone | README documents `gh auth login`; pre-indexed DB ships with the demo so judges don't need to re-index to see results |
| 7 | `fastembed` model download blocks first run | Pre-warm during install; document expected 30s first-run download |
| 8 | Time overrun on landing page polish | Locked to single static HTML; resist any framework temptation |

---

## 10. Success criteria

Binary self-assessment for Wednesday morning:

**Phase 1 (core MVP — DONE):**
- [x] Pre-indexed synthetic `acme-billing-api/` repo, ≥40 atoms across ≥5 topics, browsable via MCP from Claude Code — **primary demo path**
- [x] Three demo questions tested; strongest one locked (Q1)
- [x] Before/after demo runs end-to-end in <3 minutes with no restart

**Phase 2 (solo-dev features — adds day-one TAM):**
- [ ] `contextlayer note "<decision>"` writes user atoms; they surface in `context_query` results within milliseconds
- [ ] `contextlayer explain` renders the indexed atoms as a usable markdown brief (stack, conventions, decisions, anti-patterns)
- [ ] `contextlayer scan` produces useful atoms on a repo with zero PRs (test against a freshly-created small repo with only `pyproject.toml` + a `README.md` + 3–5 source files)

**Phase 3 (polish + distribution):**
- [ ] (Stretch) Pre-indexed `tiangolo/fastapi` repo, ≥100 atoms across ≥10 topics — **optional credibility upgrade, not required**
- [ ] Landing page live at `contextlayer.vercel.app`, waitlist form functional
- [ ] 5-minute demo video recorded, edited, captioned
- [ ] Slide deck (8–10 slides): problem → demo → market → model → roadmap → team → ask
- [ ] Public GitHub repo with clean README, architecture diagram, install one-liner, MIT license
- [ ] BYOK config documented in README — users add their own `ANTHROPIC_API_KEY`
- [ ] `uvx contextlayer` install path tested end-to-end on a clean machine

**v1.1 design completeness (for the deck, not the build):**
- [x] `context_validate` MCP tool fully designed (§5.7.4)
- [x] `contextlayer health` Repo Health Score fully designed (§5.7.5)

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

## Appendix A — Design decisions log (23 hardenings applied)

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
| 16 | 1, 3, 8, 9, 10 | **Swap primary ↔ backup demo repos.** Synthetic `acme-billing-api/` becomes PRIMARY; `tiangolo/fastapi` becomes optional "wow if time" stretch | The synthetic repo is deterministic, fast to re-index live on stage, and has dramatic atoms by construction. Pinning the critical path to a real OSS repo introduced timeline risk (PR ingestion variance, weak/diffuse atoms, gh-CLI rate limits) for marginal credibility upside. FastAPI is better staged as a post-MVP credibility upgrade |
| 17 | 5.5 | Build the MCP server on the official [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | Don't roll stdio framing / JSON-RPC / capability negotiation from scratch. Battle-tested SDK collapses ~1 day of plumbing into hours; lets us focus on retrieval and tool logic; gives judges a clean "built on Anthropic's MCP SDK" signal |
| 18 | implementation plan | **Sequence: end-to-end MVP demo by ~hour 20, polish from hour 20 → 48.** Not pipeline-then-MCP-then-demo linearly | The linear approach risks having no shippable demo until hour 47. MVP-first guarantees a working before/after artifact early; remaining time goes to quality (atom richness, prompt caching, batching, extended thinking, demo polish, landing page) with an always-shippable fallback. Logged here for traceability; lives in the hour-by-hour plan |
| 19 | 5.7.1 | **Add `contextlayer scan` — thin code-aware ingestion adapter for Phase 2.** Scans manifests, README, and top-N source files via the existing pipeline | Expands TAM from "teams with mature PR cultures" to "anyone with a Git repo." Without this, ContextLayer is unusable for the majority of solo devs and small OSS projects on day one. Thin slice (manifests + README + top files) ships in v1; AST extraction defers to v1.1 |
| 20 | 5.7.2 | **Add `contextlayer note` Decision Journal CLI for Phase 2.** User-authored atoms, $0 cost, milliseconds to write | Solo devs don't write PR descriptions but they do make decisions. This is the structured-commit-message equivalent for those decisions. Trivial to implement (no pipeline call), high adoption value, demoable as a one-beat extension of the rehearsal |
| 21 | 5.7.3 | **Add `contextlayer explain` Onboarding Doc generator for Phase 2.** Renders atoms as a polished markdown brief | Solves the "let me re-explain my project every session" tax that every solo dev pays daily. Composition of existing pieces (no new pipeline, no new storage). Becomes the artifact judges hold in their hands |
| 22 | 5.7.4 | **Design (not build) `context_validate` MCP tool for v1.1.** Anti-pattern detection at code-finalization time | The retrieval-only design is pull-based; the agent has to remember to ask. Push-based validation catches the moments that matter most. Designed now so judges can see the v1.1 roadmap; ships at OSS launch with prompt-tuning time the hackathon doesn't have |
| 23 | 5.7.5 | **Design (not build) `contextlayer health` Repo Health Score for v1.1.** Standalone CLI with consistency, coverage, drift sub-scores | A wedge that delivers standalone value before MCP wiring — same playbook as Lighthouse for web perf. Strong Show HN hook. Designed now so the OSS launch arc is concrete in the deck; ships at v1.1 |

---

## Appendix B — Roadmap (v1.1 and beyond)

Ordered by likely sequencing. v1.1 items are designed in §5.7.4–5.7.5 and Appendix A entries 22–23.

**v1.1 — OSS launch (target: 2–3 weeks post-hackathon)**

1. **`context_validate` MCP tool + `contextlayer validate` CLI** — real-time anti-pattern detection (design in §5.7.4)
2. **`contextlayer health` CLI** — Repo Health Score with consistency, coverage, drift sub-scores (design in §5.7.5)
3. **AST-based pattern extraction** in `contextlayer scan` — higher-fidelity convention detection beyond the thin v1 slice
4. **Polish the OSS release** — better install UX, error messages, docs
5. **Anthropic Batches API for Haiku stage** — 50% additional cost reduction on bulk indexing (24h latency acceptable in batch mode)

**v1.2 — adoption + integrations**

6. **Optional anonymous telemetry** — privacy-respecting, opt-in; counts of indexes/queries to understand adoption
7. **Slack ingestion adapter** — OAuth + Slack export parsing
8. **Linear ingestion adapter** — OAuth + Linear API
9. **ADR file ingestion** — markdown walker for `**/{ADR,decisions,architecture}*.md`
10. **Cursor / Cody / Aider MCP testing** — verify cross-agent compatibility

**v2 — hosted tier + teams**

11. **Hosted SaaS tier** — managed indexing, multi-tenant SQLite or Turso
12. **Team-wide knowledge sharing** — shared index across team members
13. **Auth + multi-user** — Clerk or Supabase Auth
14. **Repo Health Score shareable badges + public scorecards**

**v3 — enterprise**

15. **Enterprise SSO** — Workos
16. **On-prem deployment** — Docker image, install docs
17. **Custom ingestion adapters** — SDK for enterprises with bespoke sources

**Cross-cutting (any version)**

18. **Documentation site** — Docusaurus or GitBook (free), once tool has >100 users
19. **Real-time updates** — auto-reindex on git push (GitHub Action or local hook)
20. **Automated test suite + CI** — pytest + GitHub Actions, with fixtures for the synthetic backup repo

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

### 5.8 The immune system (v2 + v3 — the moat)

Everything in §5.7 is a productivity feature. The features in this section are a different category — they're what makes ContextLayer the *infrastructure layer that prevents production incidents*, and they're what makes the company defensible against any incumbent (Cursor, GitHub Copilot, Anthropic's own tools) that might try to absorb the productivity layer.

| | §5.7 features | §5.8 features |
|---|---|---|
| Time orientation | Describe the past | Act on the present, predict the future |
| Cadence | Static snapshot | Continuously updating |
| Replicable manually? | Yes, with effort | No, requires scale + automation |
| Buying argument | Productivity | Business continuity, incident prevention |
| Budget unlock | Per-seat | Enterprise / risk / security |

**These do not ship for the hackathon.** They are fully designed below so the deck has a credible v2/v3 story, judges can probe the moat, and the implementation work is bounded when the time comes.

#### 5.8.1 Convention Drift Detection — v2

**The thesis.** Most codebases don't die from bad decisions. They die from slow divergence. A convention gets established in month 2. By month 8, 40% of new code quietly violates it. No single PR is obviously wrong, so no review catches it. Then production breaks and nobody remembers why the convention existed in the first place.

`CLAUDE.md` cannot detect this. Static rules cannot detect this. No manual process scales to detect this across a real codebase. ContextLayer can, because it already has the conventions extracted as atoms and it already knows how to validate code against them (§5.7.4).

**Design.**

```
For each new commit (since last drift scan):
  1. Walk the diff hunks
  2. For each touched file, retrieve atoms with scope matching the path
  3. Run context_validate (§5.7.4) on the new code against those atoms
  4. Record per-convention violation count + total opportunity count
     in a drift_events table

Aggregated nightly (or on-demand):
  drift_rate(convention, window) =
      violations_in_window / opportunities_in_window

Alert when:
  - drift_rate(c, last_30d) > threshold (default 25%)
  - AND drift_rate(c, last_30d) > 2 × drift_rate(c, prior_30d)
  - i.e. "this convention used to be followed, now it isn't"
```

**Output.** Three surfaces:

1. **CLI:** `contextlayer drift` shows a ranked list of conventions with rising violation rates plus the offending commits.
2. **MCP tool:** `context_drift_report(window_days: int = 30)` — agents can ask "what's drifting in this codebase right now?" before proposing architectural changes.
3. **Optional hook:** post-merge git hook or GitHub Action that runs drift check on every merge to main and posts to Slack/Discord webhook when a convention crosses threshold.

**Storage additions:**

```sql
CREATE TABLE drift_events (
  id            TEXT PRIMARY KEY,
  atom_id       TEXT REFERENCES atoms(id),
  commit_sha    TEXT NOT NULL,
  file_path     TEXT NOT NULL,
  verdict       TEXT NOT NULL,         -- 'violation' | 'compliance' | 'na'
  severity      REAL,
  detected_at   TEXT NOT NULL
);

CREATE INDEX idx_drift_atom_time ON drift_events(atom_id, detected_at);
```

**Effort estimate.** ~3 weeks of focused work for a polished v2 release: incremental diff scanning, drift-rate computation, the CLI surface, the MCP tool, and the optional GitHub Action.

**Why this is the buying argument that wins enterprise.** A CTO doesn't approve $50K/year for "our developers will be more productive." A CTO approves $50K/year for "this prevents the kind of slow-drift architectural decay that caused our last three production incidents." Drift detection is what gets the budget.

#### 5.8.2 The Failure Loop — v2

**The thesis.** Every team learns the same lessons repeatedly. Senior engineer warns about something, gets ignored, incident happens, postmortem written, postmortem forgotten in Confluence, next engineer makes the same mistake. The cycle is universal and expensive.

ContextLayer can break it. The codebase can learn from its own failures *automatically* — once, permanently, surfaced to every future AI session.

**Design.**

```
Incident reported (any of:)
  - User runs:  contextlayer incident "billing webhook retries stormed prod"
                                       --files src/billing/webhooks.py
                                       --commits a3f1c2,b4e9d8
                                       --postmortem postmortem.md
  - Sentry/Datadog webhook posts an incident event
  - Git commit message contains "[incident]" or "[postmortem]" trailer
        ↓
ContextLayer traces back:
  - Which atoms applied to those files at incident time?
  - Which atoms were silently violated by the offending commits?
  - What code patterns are common across the implicated files?
        ↓
Sonnet drafts a candidate anti-pattern atom:
  { category: "anti-pattern",
    summary: "Don't retry webhook delivery without exponential backoff
              + jitter for billing endpoints",
    rationale: "Caused incident INC-2026-019 (billing storm 2026-08-04)",
    scope: "src/billing/webhooks/**",
    source_refs: ["incident:INC-2026-019", "postmortem:pm-019.md",
                  "commit:a3f1c2"],
    confidence: 0.9 }
        ↓
User reviews and confirms (one keystroke in the CLI).
        ↓
Atom is promoted to is_rule=1 (always-on context) and surfaces in
context_query + context_validate for every future agent session.
```

**The killer outcome.** Six months later, a new engineer (or a fresh Claude Code session) writes a webhook handler. Claude Code calls `context_validate` before finalizing. ContextLayer returns: *"This handler retries without backoff. Caused incident INC-2026-019 in this exact module. See postmortem pm-019.md."* The mistake doesn't repeat.

**Required adjacent build:** the optional Sentry/Datadog webhook integration is a thin v2.1 add-on. The CLI-driven path (`contextlayer incident`) is the v2 deliverable.

**Effort estimate.** ~1 week on top of drift detection. Most of the machinery (atom storage, validation, retrieval) already exists. New work: the incident ingestion command, the tracing logic, and the candidate-atom review flow.

**Storage additions:**

```sql
CREATE TABLE incidents (
  id            TEXT PRIMARY KEY,     -- e.g. INC-2026-019 or auto-generated
  title         TEXT NOT NULL,
  summary       TEXT,
  postmortem_md TEXT,
  source_refs   TEXT NOT NULL,        -- JSON: commits, files, dates
  resolved      INTEGER DEFAULT 0,
  created_at    TEXT NOT NULL
);

-- atom.source_refs already supports "incident:..." prefix, no schema change there
```

#### 5.8.3 Cross-Repo Intelligence — v3 (the network effect moat)

**The thesis.** Drift detection and the failure loop are powerful per repo. They get *more* powerful with scale, because patterns repeat across teams. Most production incidents have been suffered before, by someone, somewhere. ContextLayer is the only system positioned to *see across repos*, anonymize the patterns, and surface the lessons.

**What it looks like for the user (illustrative outputs):**

> *"Teams using FastAPI + async at your scale: 78% regret not adding connection pooling before 50k DAU. You don't have it."*

> *"The auth pattern you are implementing matches a pattern that caused security incidents in 23 other repos. Here's what the 23 teams did to remediate."*

> *"Your error handling approach is consistent with 12% of Python repos in our network. Here's what the other 88% switched to and why."*

**Why this is the moat.** Manually unreplicable. Requires aggregate data only ContextLayer has. The more users, the smarter it gets for every user — classic network-effect economics. A new competitor at year 3 cannot bootstrap this without our user base.

**Design.**

Three components, all hosted-tier features:

1. **Anonymized telemetry (opt-in).** Per indexed repo, ContextLayer can optionally upload: atom shapes (no rationale text by default — just category, scope glob, embedding), incident metadata (no postmortem content), and tech-stack signals (manifest entries). Privacy-respecting by construction — no source code, no commit messages, no PII. Single toggle: `contextlayer telemetry on`.

2. **Pattern matching service (cloud).** When a user runs `contextlayer scan` or queries via MCP, the local client can ask the cloud: *"For repos matching this stack signature, what atoms are most common, what incidents are most common, what conventions correlate with low-drift outcomes?"* Returns anonymized aggregate results.

3. **Insight surfacing (cloud + MCP).** New MCP tool `context_compare(scope)` returns peer-cohort insights. CLI `contextlayer insights` shows them as a report.

**Privacy posture.** This is the make-or-break of the v3 design. Defaults:

- Telemetry is **opt-in**, not opt-out
- No source code, no PR text, no commit messages, no postmortem prose ever leaves the user's machine
- Atom summaries are optionally redacted (user can mark atoms `private: true`)
- Aggregate insights only surface when cohort size ≥ 50 repos (k-anonymity)
- Open-source the anonymization pipeline so users can audit what's sent

**Effort estimate.** ~2–3 months for v3 launch. Substantial because it requires real cloud infrastructure: anonymization pipeline, multi-tenant aggregate store, opt-in flow with clear privacy UX, k-anonymity enforcement, and the MCP tool + CLI surface.

**Why this is the acquisition-defining feature.** Anthropic, GitHub, or Cursor could build the productivity layer themselves. They cannot easily build a cross-repo intelligence layer because they don't have repo coverage — and even if they tried, the privacy posture would be a wall for enterprise adoption from any of them. ContextLayer, as a neutral open-source project with a clear privacy story, is uniquely positioned to be the trusted network. That's the leverage that turns this from a feature into an acquisition target.

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
- [x] Pre-indexed synthetic `acme-billing-api/` repo, **15 canonical atoms across 7 topics, 8 rules** (Opus dedup collapsed 67 raw → 15 high-signal canonical), browsable via MCP from Claude Code — **primary demo path**
- [x] Three demo questions tested; strongest one locked (Q1)
- [x] Before/after demo runs end-to-end in <3 minutes with no restart

> **Note on the atom-count threshold:** spec was originally written assuming "≥40 atoms" before Opus structuring shipped. Post-Opus, 15 deduplicated canonical atoms (with 8 promoted to rules) is the right shape — the threshold was a proxy for coverage, and coverage is now better measured by topic count (7) and the four demo-critical conventions all being present as rules at confidence ≥0.95.

**Phase 2 (solo-dev features — adds day-one TAM):**
- [x] `contextlayer note "<decision>"` writes user atoms; they surface in `context_query` results within milliseconds — verified, JWT-expiry note in DB
- [x] `contextlayer explain` renders the indexed atoms as a usable markdown brief (stack, conventions, decisions, anti-patterns) — Jinja2 template, ships at `src/contextlayer/templates/explain.md.j2`
- [x] `contextlayer scan` produces useful atoms on a repo with zero PRs — code-only ingestion path lands in `src/contextlayer/ingest/code_scan.py`

**Phase 2B (pipeline + retrieval polish):**
- [x] Stage 3 Opus with extended thinking (dedup + topic clustering + rule promotion)
- [x] Prompt caching on Haiku + Sonnet (system prompt + tools prefix)
- [x] Sonnet batching at 15 events/call (with graceful per-event fallback)
- [x] Per-event idempotency cache (`ingest_cache` table) — reruns are near-free
- [x] Hybrid retrieval (cosine + keyword Jaccard + rule boost + recency) — locked-Q1 returns all 4 canonical atoms in top-5

**Phase 3 (polish + distribution):**
- [ ] (Stretch) Pre-indexed `tiangolo/fastapi` repo, ≥100 atoms across ≥10 topics — **optional credibility upgrade, not required**
- [x] Landing page at `landing/index.html` (Tailwind CDN, Inter font, hero/demo/features/waitlist sections) — *deploy to Vercel pending*
- [ ] 5-minute demo video recorded, edited, captioned — **largest remaining item**
- [x] Slide deck (8 slides): problem → solution → demo → architecture → solo-dev → market → business+moat → roadmap+ask. Lives at `docs/slide-deck.md`; PDF export pending
- [x] Public GitHub repo with clean README, architecture diagram, install one-liner, MIT license
- [x] BYOK config documented in README — users add their own `ANTHROPIC_API_KEY`
- [ ] `uvx contextlayer` install path tested end-to-end on a clean machine — **gated on PyPI publication**

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

## Appendix A — Design decisions log (26 hardenings applied)

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
| 24 | 5.8.1 | **Design (not build) Convention Drift Detection for v2.** Continuous monitoring + per-convention drift-rate alerts | The buying argument that unlocks enterprise budget. Productivity features don't get $50K/yr approval; "prevents the slow architectural drift that caused our last three incidents" does. Designed now so the deck's enterprise tier is credible |
| 25 | 5.8.2 | **Design (not build) The Failure Loop for v2.** Incident → traced atoms → auto-extracted anti-pattern → permanent warning for future sessions | Breaks the "every team learns the same lessons repeatedly" cycle. The codebase becomes its own postmortem archive — queryable, scoped, surfaced to every AI agent that touches relevant code |
| 26 | 5.8.3 | **Design (not build) Cross-Repo Intelligence for v3.** Anonymized aggregate insights across the user network | The network-effect moat. Impossible to replicate without ContextLayer's user base. Privacy-first design (opt-in, k-anonymity, no source code transmitted) keeps enterprise trust intact. This is the acquisition-defining feature |

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

**v2 — the immune system (the buying argument for enterprise)**

11. **Convention Drift Detection** (design in §5.8.1) — `contextlayer drift` CLI + `context_drift_report` MCP tool + optional GitHub Action
12. **The Failure Loop** (design in §5.8.2) — `contextlayer incident` CLI + traced anti-pattern auto-extraction + Sentry/Datadog webhook integration (v2.1)
13. **Hosted SaaS tier** — managed indexing, multi-tenant SQLite or Turso
14. **Team-wide knowledge sharing** — shared index across team members
15. **Auth + multi-user** — Clerk or Supabase Auth
16. **Repo Health Score shareable badges + public scorecards**

**v3 — network effects + enterprise (the moat)**

17. **Cross-Repo Intelligence** (design in §5.8.3) — anonymized telemetry, peer-cohort insights, `context_compare` MCP tool, k-anonymity privacy guarantees
18. **Enterprise SSO** — Workos
19. **On-prem deployment** — Docker image, install docs
20. **Custom ingestion adapters** — SDK for enterprises with bespoke sources

**Cross-cutting (any version)**

21. **Documentation site** — Docusaurus or GitBook (free), once tool has >100 users
22. **Real-time updates** — auto-reindex on git push (GitHub Action or local hook)
23. **Automated test suite + CI** — pytest + GitHub Actions, with fixtures for the synthetic backup repo

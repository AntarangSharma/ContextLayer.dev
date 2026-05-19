# ContextLayer.dev — Personal Usage Guide
**Post-Hackathon Setup | What it actually costs, what's actually free**

---

## What you're setting up

ContextLayer has two pieces:
- **Indexer** — runs occasionally, reads your repo, calls the Anthropic API, writes to local SQLite. **Costs money** (token usage).
- **MCP server** — runs while you code, serves context to Claude Code via stdio. **Always free** (pure local lookup, zero API calls).

So the only thing you ever pay for is `contextlayer index`.

---

## Honest cost breakdown

Per-repo indexing cost using the current pipeline (Haiku → Sonnet → Opus, all Anthropic):

| Stage | Model | Typical cost |
|---|---|---|
| Filter | Haiku | $0.05–0.15 |
| Extract | Sonnet | $0.20–0.40 |
| Structure | Opus | $0.80–1.00 |
| **Per index run** | | **~$1.05–$1.55** |

Re-runs are near-free — the idempotency cache skips events that were already processed, so only new commits/PRs hit the API. A typical "I made 5 commits since last index" rerun costs cents.

---

## How to keep this cheap

### 1. Use hackathon credits if you have them

If you got $500 in Anthropic credits at the hackathon, you can index ~300–500 repos before paying anything. At one index per repo + cheap re-runs after, that's a year of personal use.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
contextlayer index .
```

### 2. Use the decision-journal path (zero API calls, ever)

`contextlayer note` writes an atom directly to the local SQLite store. No model runs. No tokens. **Free.** This is the fastest way to make a repo "ContextLayer-aware" without paying anything — works on day one, including on repos where you skip `index` entirely.

```bash
contextlayer note "all timestamps are UTC; never localize at storage layer" --scope "src/**"
contextlayer note "switched from axios to fetch — bundle size was 40kb over budget"
contextlayer note "auth tokens expire in 7d" --rationale "agreed with security team 2026-05-15"
```

Then start the MCP server normally — Claude Code can query these notes via `context_query` immediately.

### 3. Use `scan` instead of `index` on repos with no PR history

`contextlayer scan` skips git+PR ingestion and only reads code (manifests, README, top source files). Fewer events → cheaper indexing.

```bash
contextlayer scan /path/to/repo
```

### 4. Re-index sparingly

The cache means subsequent runs are cheap, but the first run on a large repo can be a few dollars. Index after meaningful merges, not after every commit.

---

## Multi-provider support (not yet — roadmap)

The current pipeline is Anthropic-only. There is no `CONTEXTLAYER_PROVIDER` env var, no Gemini/Ollama/Groq adapter. Earlier versions of this guide promised these — they don't exist yet.

If you need a non-Anthropic path today, your options are:
- **Use credits.** Hackathon credits cover hundreds of indexes.
- **Use `note` only.** Skip `index` entirely, populate the store manually with `contextlayer note`. Zero API cost, zero provider lock-in.
- **Wait.** Multi-provider support is on the roadmap; track the repo if you need it.

---

## Daily usage

### Start a coding session

```bash
# Terminal 1: start the MCP server (stdio — keep this running)
cd /path/to/your/repo
contextlayer mcp --repo .

# Terminal 2: start Claude Code as normal
claude
```

The MCP server is stdio-only — there is no `--port` flag, no HTTP server. Each Claude Code session connects over stdin/stdout via the `.mcp.json` config below.

### Update the index after meaningful changes

```bash
cd /path/to/your/repo
contextlayer index .
```

Idempotent. Only new events hit the API.

### Inspect what's been extracted

```bash
contextlayer status --repo .         # atom count, topic count, rule count, last index time
contextlayer explain --out BRIEF.md  # generate a markdown project brief from atoms
```

There is no `contextlayer query`, `contextlayer topics`, or `contextlayer list` CLI command — those were aspirational in an earlier draft of this guide and don't exist. To query atoms, use the `context_query` MCP tool from inside Claude Code, or read the SQLite file directly at `~/.contextlayer/<repo-hash>/index.db`.

### Add a decision

```bash
contextlayer note "your decision here"
contextlayer note "your decision" --scope "src/api/**" --rationale "why"
```

---

## Connecting to Claude Code

Add a `.mcp.json` to your repo root (Claude Code reads this automatically):

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "uvx",
      "args": ["contextlayer-dev", "mcp", "--repo", "."]
    }
  }
}
```

Or use the brand command if you've `pip install`-ed:

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "contextlayer",
      "args": ["mcp", "--repo", "."]
    }
  }
}
```

Verify inside a Claude Code session with `/mcp` — `contextlayer` should appear as connected.

> The PyPI distribution is **`contextlayer-dev`** because the bare `contextlayer` name on PyPI was taken before we shipped. The installed CLI binary is still `contextlayer`. Both `contextlayer …` and `contextlayer-dev …` work after install.

---

## Connecting to Cursor

`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "uvx",
      "args": ["contextlayer-dev", "mcp", "--repo", "."]
    }
  }
}
```

---

## Multiple repos

Each repo gets its own index keyed by repo path hash (see `index_db_path()` in [src/contextlayer/store/repo_hash.py](src/contextlayer/store/repo_hash.py)). Just run `contextlayer index .` in each repo. Each Claude Code session loads the MCP server with `--repo <that-repo>` via its own `.mcp.json`.

There is no "multiple servers on different ports" setup — the server is stdio per Claude Code instance.

---

## Troubleshooting

**`No index found at <path>`**
You haven't run `contextlayer index .` (or `contextlayer scan .`, or `contextlayer note "..."`) yet for this repo. Any of the three creates the DB.

**`ANTHROPIC_API_KEY is not set`**
`export ANTHROPIC_API_KEY=sk-ant-...` before running `index` or `scan`. Not needed for `mcp`, `note`, `explain`, `status`, or `claude-md` — those are pure-local.

**Rate-limit errors during indexing**
The pipeline rate-limits globally (default 50 RPM). Override with `CONTEXTLAYER_RPM_LIMIT=30` (or lower) if your account's per-minute cap is tighter.

**Want to start fresh**
```bash
# Index DB lives under ~/.contextlayer keyed by repo hash; see store/repo_hash.py
rm -rf ~/.contextlayer
contextlayer index .
```

**Indexed atoms look thin / low quality**
Happens on small repos or repos with minimal PR descriptions. Use `contextlayer note` to fill the gaps with decisions you remember.

---

## What ContextLayer reads vs doesn't

**It reads:**
- `git log` (commit messages)
- `gh` CLI output (PR titles, descriptions, review comments) — requires `gh auth login`
- Code scan (manifests, README, top source files)
- `contextlayer note` entries

**It doesn't read (today):**
- Slack, email, chat — anywhere decisions live outside the repo
- Code comments — planned
- Issues/tickets — planned

**Practical implication:** if your team decides in Slack and never writes it in PRs, ContextLayer won't see it. `contextlayer note` is the bridge — use it.

---

## Quick reference

```bash
# Install
pip install contextlayer-dev          # or: uvx contextlayer-dev <command>

# Index (costs money — needs ANTHROPIC_API_KEY)
export ANTHROPIC_API_KEY=sk-ant-...
contextlayer index .                  # full pipeline
contextlayer scan .                   # code-only, cheaper

# Free, local-only
contextlayer note "decision text"     # capture a decision atom (no API call)
contextlayer status --repo .          # show counts + last index time
contextlayer explain --out BRIEF.md   # render a project brief from atoms
contextlayer claude-md                # print the CLAUDE.md snippet
contextlayer mcp --repo .             # start the stdio MCP server
```

---

*ContextLayer.dev — built at the State of Oregon Claude Code Hackathon, May 2026*
*Repo: https://github.com/AntarangSharma/ContextLayer.dev*

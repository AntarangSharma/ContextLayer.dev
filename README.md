# ContextLayer.dev

**The missing context layer for AI coding agents.**

Every codebase has unwritten rules — *why-this-not-that* decisions, team conventions, deprecated paths, anti-patterns — buried in PR comments, commit messages, and senior engineers' heads. Every AI agent rediscovers them badly, every session. ContextLayer extracts these as structured "knowledge atoms" and serves them to Claude Code (or any MCP client) so your AI answers like a senior engineer who read everything.

```
Same Claude Code. Same question. Watch the answer change.
```

---

## ⚡ Quick Start (30 seconds)

```bash
# 1. Install & index your repo
pip install contextlayer
export ANTHROPIC_API_KEY=sk-ant-...   # BYOK — bring your own key
contextlayer index .

# 2. Add MCP to your repo
cat >> .mcp.json << 'EOF'
{
  "mcpServers": {
    "contextlayer": {
      "command": "uvx",
      "args": ["contextlayer", "mcp", "--repo", "."]
    }
  }
}
EOF

# 3. Open Claude Code — it now knows your team's conventions
```

Or use `uv` (recommended):

```bash
uvx contextlayer index .
```

---

## 🔍 What It Does

ContextLayer reads your repo from **three sources** and extracts structured knowledge atoms:

| Source | What it captures |
|---|---|
| **Git history** | Commit messages, PR descriptions, review comments |
| **Code structure** | Manifests, README, top source files — conventions from the code itself |
| **Decision journal** | Your own notes: `contextlayer note "all timestamps are UTC"` |

A multi-agent pipeline processes these through three models:

```
Haiku (filter)  →  Sonnet (extract)  →  Opus (structure)
 ~5000 events       ~500 kept            ~40 canonical atoms
 "is this a rule?"  "extract the atom"   "dedup + topics + rules"
```

The result: a local SQLite knowledge store served to Claude Code via MCP.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│  CLI (one-shot):  $ contextlayer index <repo>                    │
│                                                                  │
│   Ingestion adapters  →  Multi-agent extraction  →  SQLite (WAL) │
│   • git log              • Haiku  (relevance filter, cached)     │
│   • gh CLI (PRs)         • Sonnet (atom extractor, batched,      │
│   • code scan              tool use, prompt cache)               │
│                          • Opus   (dedup + structure, 1 call,    │
│                            extended thinking enabled)            │
└──────────────────────────────────────────────────────────────────┘
                                                          │
                                                          │ same DB file
                                                          ▼
┌──────────────────────────────────────────────────────────────────┐
│  MCP server (long-running):  $ contextlayer mcp --repo .         │
│                                                                  │
│   Tools exposed to Claude Code:                                  │
│   • context_query(question, k=5) → relevant atoms + citations    │
│   • context_list_topics() → discovered topic clusters            │
│                                                                  │
│   Retrieval: hybrid (cosine similarity + keyword overlap         │
│              + recency boost)                                    │
└──────────────────────────────────────────────────────────────────┘
                                  ▲
                                  │ stdio
                                  │
                            Claude Code
```

---

## 📦 CLI Commands

| Command | What it does |
|---|---|
| `contextlayer index <repo>` | Run full pipeline (git + PR + code scan) → atoms → SQLite |
| `contextlayer scan <repo>` | Code-only ingestion — works on repos with zero PR history |
| `contextlayer mcp --repo <path>` | Start the MCP server (stdio transport) |
| `contextlayer note "<decision>"` | Capture a decision directly — no API call, free, instant |
| `contextlayer explain` | Generate a markdown project brief from indexed atoms |
| `contextlayer status --repo <path>` | Show atom count, topics, rules, last index time |
| `contextlayer claude-md` | Print the CLAUDE.md snippet to append to your repo |

### Decision Journal — works on any repo, day one

```bash
# Capture decisions as you make them — zero cost, milliseconds
contextlayer note "switched from axios to fetch — bundle size win"
contextlayer note "all timestamps are UTC; never localize at storage layer" --scope "src/**"
contextlayer note "auth tokens expire in 7d" --rationale "agreed with security team 2026-05-15"
```

### Onboarding Doc — skip the "explain my project" tax

```bash
# Generate a project brief from indexed atoms
contextlayer explain --out PROJECT_BRIEF.md
```

---

## 🧠 Knowledge Atoms

An atom is a structured piece of team knowledge:

```json
{
  "category": "convention",
  "summary": "Use Result<T> for domain errors, not exceptions",
  "rationale": "PR #421 — exceptions broke async tracing in Q3 incident",
  "scope": "src/api/**",
  "source_refs": ["pr:421", "commit:abc123"],
  "confidence": 0.95,
  "is_rule": true
}
```

Categories: `convention` · `decision` · `deprecation` · `anti-pattern` · `user_decision`

---

## 💰 Cost

ContextLayer uses a BYOK (Bring Your Own Key) model. You provide your Anthropic API key.

| Component | Cost per repo indexed |
|---|---|
| Haiku (filter) | ~$0.05–0.15 |
| Sonnet (extract) | ~$0.20–0.40 |
| Opus (structure) | ~$0.80–1.00 |
| **Total** | **~$1.05–$1.55** |

Re-runs are near-free thanks to per-event idempotency caching.

---

## 🛠 Configuration

**API Key:** Set `ANTHROPIC_API_KEY` in your environment. Never stored on disk.

```bash
export ANTHROPIC_API_KEY=sk-ant-api03-...
```

**MCP Setup:** Add to `.mcp.json` at your repo root:

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

**CLAUDE.md nudge** (recommended — makes Claude Code proactively query):

```markdown
## ContextLayer

This repo has a ContextLayer knowledge index. Before proposing code changes,
call the `context_query` MCP tool with what you intend to do — the repo has
codified team conventions and prior decisions; respect them.
```

---

## 🗺️ Roadmap

| Version | Timeline | Features |
|---|---|---|
| **v1** (current) | Hackathon | CLI + MCP server, multi-agent pipeline, solo-dev features |
| **v1.1** | +3 weeks | `context_validate` (real-time anti-pattern detection), Repo Health Score |
| **v2** | +3 months | Convention Drift Detection, Failure Loop (incident → auto-extracted atoms) |
| **v3** | +6 months | Cross-Repo Intelligence (anonymized network effects across repos) |

---

## 🏛️ Built With

- [Anthropic Claude](https://anthropic.com) — Haiku, Sonnet, Opus (multi-agent pipeline)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) — stdio MCP server
- [fastembed](https://github.com/qdrant/fastembed) — BGE-small-en-v1.5 embeddings (ONNX, lightweight)
- [SQLite WAL](https://sqlite.org/wal.html) — local-first atom storage
- [Typer](https://typer.tiangolo.com) — CLI framework

---

## 📄 License

MIT — [LICENSE](LICENSE)

---

**ContextLayer.dev** — *Your Claude Code answers like a senior engineer who read everything.*
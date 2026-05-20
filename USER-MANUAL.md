# ContextLayer — User Manual

**Plain-English guide for new users. No jargon. Read time: 5 minutes.**

---

## 1. What is ContextLayer?

When you ask Claude (or any AI assistant) to write code for *your* project, it doesn't know your team's rules — things like "we never use threading" or "always return Result<T>" or "don't share database sessions."

ContextLayer fixes that. It reads your repo's history (git commits + pull requests) once, extracts the **unwritten rules** into a small local database, and feeds them back to your AI assistant when needed.

**Result:** Your AI stops giving generic advice and starts following your team's actual conventions.

---

## 2. What you need

- **Python 3.11 or newer**
- **A code editor that speaks MCP** (Claude Code, Claude Desktop, Cursor, etc.)
- **(Optional) An Anthropic API key** — only needed if you want to build a new index for your own repo, or use the premium accuracy tier.

You can try ContextLayer **with zero setup** using the bundled demo (see Section 4).

---

## 3. Install

```bash
pip install contextlayer-dev
```

Or, with uv (recommended — no venv needed):

```bash
uvx contextlayer-dev --help
```

> The package is named **`contextlayer-dev`** on PyPI (the bare `contextlayer` name
> was taken before we shipped). The installed CLI binary is the brand command,
> **`contextlayer`** — so `contextlayer …` and `contextlayer-dev …` both work after
> install.

Check it worked:

```bash
contextlayer --help
```

---

## 4. The 30-second test drive (no API key needed)

Clone the repo, then point ContextLayer at the demo data:

```bash
git clone https://github.com/AntarangSharma/ContextLayer.dev.git
cd ContextLayer.dev
```

The demo comes pre-indexed. Ask a question:

```bash
contextlayer status --repo demo-data/acme-billing-api
```

You should see something like *"67 atoms, 7 topics, 8 rules"*. That means the knowledge is ready.

---

## 5. The three tiers — choose how it runs

ContextLayer has three modes. You pick one by setting an environment variable:

```bash
export CONTEXTLAYER_TIER=free      # or hybrid, or premium
```

| Tier | Needs API key? | What it does |
|---|---|---|
| **free** | No | Uses local rules only. Fast and free, slightly less smart. |
| **hybrid** (default) | Optional | Uses local rules first; only asks Claude when unsure. Best balance. |
| **premium** | Yes | Always asks Claude. Highest accuracy, costs pennies per check. |

If you don't set anything, you get **hybrid** mode automatically. If you don't have an API key, hybrid silently behaves like free — nothing breaks.

---

## 6. Index your own repo (optional — needs API key)

If you want ContextLayer to learn *your* project's rules instead of the demo:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
contextlayer index /path/to/your/repo
```

This reads your git history and pull requests, then writes a small database to `~/.contextlayer/<repo-id>/index.db`. It runs once and takes a few minutes for a typical repo.

If your repo doesn't have many pull requests, use this instead — it reads your code files directly:

```bash
contextlayer scan /path/to/your/repo
```

---

## 7. Connect ContextLayer to your AI assistant

ContextLayer talks to AI tools using **MCP** (Model Context Protocol). Setup takes one minute.

### For Claude Code

Generate a topic-grouped, citation-inlined `CLAUDE.md` from your indexed atoms
(or append to an existing one):

```bash
contextlayer claude-md --output CLAUDE.md            # write fresh
contextlayer claude-md --output CLAUDE.md --append   # extend existing
```

Then start the ContextLayer server from your repo:

```bash
contextlayer mcp --repo .
```

Claude Code will see three new tools:

- **`context_query`** — search your team's rules
- **`context_list_topics`** — see what topics ContextLayer knows about
- **`context_validate`** — check a proposed change against your rules

Claude Code will call them automatically when relevant.

### For Claude Desktop / Cursor / other MCP clients

Add this to your MCP config file (path varies by app):

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "contextlayer",
      "args": ["mcp", "--repo", "/absolute/path/to/your/repo"]
    }
  }
}
```

Restart the app. Done.

---

## 8. Daily use — what you actually do

Once it's connected, you don't run any commands. You just chat with your AI normally.

**Example.** You tell Claude:

> *"Add an endpoint that fetches a user's billing history."*

Without ContextLayer, Claude writes a generic FastAPI endpoint that ignores your conventions.

With ContextLayer, Claude **automatically** calls `context_query` first, gets back your team's rules, and writes code that:
- Returns `Result<T>` (your error convention)
- Is `async def` (your async-first rule)
- Uses `Depends(get_session)` (your session-handling rule)
- Doesn't share sessions across requests

It also cites the original pull requests so you can verify.

---

## 9. Add your own rule on the fly

Found a convention that isn't in the index yet? Just write a note:

```bash
contextlayer note "Never call time.sleep() in route handlers — use asyncio.sleep instead."
```

That note becomes a rule the next time Claude asks. No re-index needed.

---

## 10. Check what ContextLayer knows

See atom / rule / topic counts and the last index time:

```bash
contextlayer status --repo .
```

Generate a plain-English **project brief** from the indexed atoms — perfect
for pasting into a fresh Claude session:

```bash
contextlayer explain --out PROJECT_BRIEF.md
```

---

## 11. 🆕 v1.1 — score your index, catch drift, publish CLAUDE.md

Three new commands turn your indexed conventions into CI-grade signals. All
three are **keyless** (no `ANTHROPIC_API_KEY` needed) and **deterministic** —
no LLM calls, no surprises.

### `contextlayer health` — how good is my index?

Scores your index **0–100 (A–F)** across six dimensions: atom count, rule
count, topic breadth, citation coverage, freshness (last 90 days), and
conflict-freedom.

```bash
contextlayer health --repo .
```

You'll see something like:

```
┌─────────────────────────────────────────┐
│  Convention Health: A+ (98/100)         │
│                                         │
│  ✓ 15 atoms extracted                   │
│  ✓ 8 rules promoted                     │
│  ✓ 7 topics discovered                  │
│  ✓ 24 PR/commit citations               │
│  ✓ No stale rules, no conflicts         │
└─────────────────────────────────────────┘
```

For dashboards or CI: `contextlayer health --json` returns the same numbers
as machine-readable JSON.

### `contextlayer drift` — did anyone break the rules?

Checks recent commits against your indexed `do not …` / `never …` / `avoid …`
rules. Exit code **1** when violations are found, so it slots straight into
CI as a pre-merge gate.

```bash
contextlayer drift --last 10               # check the last 10 commits
contextlayer drift --since "7 days ago"    # or by date window
```

Sample output:

```
⚠ 1 potential violation found:

  commit def5678 (5 days ago) "Quick fix: use db_helper for migration"
  ┗━ Violates rule a_2598: "Do not use utils/db_helper"
     Source: PR #8
     Matched: utils/db_helper
```

It only flags negative-obligation rules with **concrete identifiers**
(snake_case, slashed, dotted, hyphenated, or camelCase). Bare English words
are skipped to keep false positives near zero.

**Drop it into GitHub Actions:**

```yaml
- name: ContextLayer drift check
  run: |
    pip install contextlayer-dev
    contextlayer drift --last 20 --repo .
```

### `contextlayer claude-md` — publish a real `CLAUDE.md`

Renders a production-quality `CLAUDE.md` from your indexed atoms — topic-
grouped, rules first, citations inlined, scopes labeled. Drop it into your
repo root and every Claude session in that directory benefits, even without
the MCP server running.

```bash
contextlayer claude-md --output CLAUDE.md           # write fresh
contextlayer claude-md --output CLAUDE.md --append  # extend an existing one
contextlayer claude-md > /tmp/brief.md              # or pipe to stdout
```

---

## 12. Common questions

**Q: Will it slow Claude down?**
No. A warm query runs in under 15 milliseconds. The first query after starting the server takes ~400 ms while the model loads.

**Q: Does it send my code anywhere?**
Only if you set `CONTEXTLAYER_TIER=premium` or use `contextlayer index`. The default hybrid tier sends nothing if you don't have an API key, and the free tier never sends anything, period.

**Q: What if I don't have an Anthropic key?**
ContextLayer still works for querying and validating — you just can't build a new index from scratch. You can either use the bundled demo, or wait for the upcoming local-LLM indexing option.

**Q: Where is the data stored?**
`~/.contextlayer/<repo-hash>/index.db` — a single SQLite file. Delete it to start over.

**Q: How do I update?**

```bash
pip install -U contextlayer-dev
```

**Q: Can I run ContextLayer in CI?**
Yes — that's what the v1.1 commands (`health`, `drift`, `claude-md`) are
built for. They're keyless, deterministic, and `drift` exits 1 on
violations. See Section 11 for a GitHub Actions snippet.

**Q: Something broke. Where do I report it?**
GitHub Issues: https://github.com/AntarangSharma/ContextLayer.dev/issues

---

## 13. The whole thing in 5 lines

1. `pip install contextlayer-dev`
2. `contextlayer index .` (or just use the demo — no key needed)
3. Add ContextLayer to your AI tool's MCP config
4. Chat with your AI normally — it now follows your team's rules
5. Add new rules with `contextlayer note "..."`, gate CI with `contextlayer drift`

That's it. Welcome to ContextLayer.

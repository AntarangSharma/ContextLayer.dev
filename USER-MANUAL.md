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
pip install contextlayer
```

Or, with uv:

```bash
uv pip install contextlayer
```

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

Add a one-time line to your `CLAUDE.md` file in any project root:

```bash
contextlayer claude-md >> CLAUDE.md
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

See the topics it discovered:

```bash
contextlayer status --repo .
```

Get a plain-English explanation of any topic or rule:

```bash
contextlayer explain "session handling"
```

---

## 11. Common questions

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
pip install -U contextlayer
```

**Q: Something broke. Where do I report it?**
GitHub Issues: https://github.com/AntarangSharma/ContextLayer.dev/issues

---

## 12. The whole thing in 5 lines

1. `pip install contextlayer`
2. `contextlayer index .` (or just use the demo — no key needed)
3. Add ContextLayer to your AI tool's MCP config
4. Chat with your AI normally — it now follows your team's rules
5. Add new rules with `contextlayer note "..."`

That's it. Welcome to ContextLayer.

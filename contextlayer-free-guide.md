# ContextLayer.dev — Free Usage Guide
**Post-Hackathon Personal Setup | Zero Cost**

---

## What You Are Setting Up

ContextLayer has two pieces:
- **Indexer** — runs once, reads your repo, calls an AI model, writes to SQLite
- **MCP Server** — runs while you code, serves context to Claude Code / Cursor

Only the indexer costs money (AI API calls). The MCP server is always free.
Goal: make the indexer free too.

---

## Cost Reality Check

| Step | Model Used | Cost (Anthropic) | Free Alternative |
|---|---|---|---|
| Filter | Haiku | ~$0.01 per repo | Gemini Flash / Llama |
| Extract | Sonnet | ~$0.30 per repo | Gemini Flash / Qwen |
| Structure | Opus | ~$0.50 per repo | Gemini Pro / Llama |
| MCP Server | None | $0 forever | $0 forever |
| **Total** | | **~$0.80 per repo** | **$0** |

You can index most repos for under $1 even with Anthropic.
But if you want $0 forever, follow the options below.

---

## Option 1: Gemini Free Tier (Recommended)

Best free option. Cloud quality, no credit card, generous limits.

### Step 1: Get Free Gemini API Key
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Sign in with Google
3. Click **Get API Key** → **Create API key**
4. Copy it somewhere safe

**Free tier limits (as of 2026):**
- Gemini 1.5 Flash: 15 requests/minute, 1 million tokens/day
- Gemini 1.5 Pro: 2 requests/minute, 50k tokens/day
- No credit card required, limits reset daily

### Step 2: Install ContextLayer
```bash
# Requires Python 3.11+
uvx contextlayer-dev --version

# Or install permanently
pip install contextlayer-dev
```

> The PyPI package is **`contextlayer-dev`** because the bare `contextlayer`
> name was taken on PyPI by an unrelated project before we shipped. The CLI
> binary stays `contextlayer` (it's a separate console-script entry point),
> so all `contextlayer …` commands below work after install.

### Step 3: Configure for Gemini
```bash
# Set environment variable
export CONTEXTLAYER_PROVIDER=gemini
export GEMINI_API_KEY=your_key_here

# Add to ~/.bashrc or ~/.zshrc to persist
echo 'export CONTEXTLAYER_PROVIDER=gemini' >> ~/.zshrc
echo 'export GEMINI_API_KEY=your_key_here' >> ~/.zshrc
source ~/.zshrc
```

### Step 4: Index Your Repo
```bash
cd /path/to/your/repo
contextlayer index .
```

Done. Index file lives at `~/.contextlayer/<repo-name>/index.db`

---

## Option 2: Ollama (Fully Local, Air-Gapped, Zero Data Leaves Machine)

Use this if you do not want any data sent to any cloud service.

### Step 1: Install Ollama
```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: download installer from ollama.com
```

### Step 2: Pull Models
```bash
# Filter step replacement (fast, small)
ollama pull llama3.2

# Extract + Structure replacement (better quality)
ollama pull qwen2.5-coder:7b

# If you have 16GB+ RAM, use this for best quality
ollama pull qwen2.5-coder:14b
```

### Step 3: Start Ollama Server
```bash
# Ollama runs as a background service automatically after install
# Verify it is running:
curl http://localhost:11434/api/tags
```

### Step 4: Configure ContextLayer for Ollama
```bash
export CONTEXTLAYER_PROVIDER=ollama
export OLLAMA_BASE_URL=http://localhost:11434
export CONTEXTLAYER_FILTER_MODEL=llama3.2
export CONTEXTLAYER_EXTRACT_MODEL=qwen2.5-coder:7b
export CONTEXTLAYER_STRUCTURE_MODEL=qwen2.5-coder:7b
```

### Step 5: Index
```bash
cd /path/to/your/repo
contextlayer index .
```

**Honest quality warning:** Ollama models are 70-80% as good as Claude at extraction.
For personal repos this is fine. For complex enterprise codebases, use Gemini.

---

## Option 3: Groq Free Tier (Fastest Free Option)

Groq runs open source models at very high speed. Free tier, no card needed.

```bash
# Get key at console.groq.com
export CONTEXTLAYER_PROVIDER=groq
export GROQ_API_KEY=your_key_here
export CONTEXTLAYER_FILTER_MODEL=llama-3.1-8b-instant
export CONTEXTLAYER_EXTRACT_MODEL=llama-3.3-70b-versatile
export CONTEXTLAYER_STRUCTURE_MODEL=llama-3.3-70b-versatile
```

---

## Option 4: Use Anthropic Credits From Hackathon

If you participated in the hackathon, you received $500 in Claude API credits.
At ~$0.80 per repo, that is **625 repos** before you pay anything.

```bash
export ANTHROPIC_API_KEY=your_hackathon_key
contextlayer index .
# Uses Haiku → Sonnet → Opus pipeline (best quality)
```

Do not overthink free alternatives if you have credits sitting unused.

---

## Daily Usage Guide

### Starting a Coding Session

```bash
# Terminal 1: start MCP server (keep this running)
cd /path/to/your/repo
contextlayer mcp --repo .

# Terminal 2: start Claude Code as normal
claude
```

Claude Code now automatically queries ContextLayer before answering.
You do not need to do anything else.

### Updating the Index

Run this after every sprint or major feature merge:

```bash
cd /path/to/your/repo
contextlayer index .
# Idempotent — only processes new commits since last run
# Fast and cheap on re-runs
```

### Querying Manually

Test what ContextLayer knows about your repo:

```bash
# See all topics extracted
contextlayer topics

# Search for a specific topic
contextlayer query "error handling"
contextlayer query "deprecated modules"
contextlayer query "authentication"

# See all extracted atoms
contextlayer list
```

### Adding Manual Decisions (Decision Journal)

For decisions you make that are not in PRs:

```bash
contextlayer note "switched from axios to fetch — bundle size was 40kb over budget"
contextlayer note "do not use threading in workers — caused race condition in issue #88"
contextlayer note "all new endpoints must use Result type not exceptions"
```

These become queryable knowledge atoms immediately.

---

## Connecting to Claude Code

Add to your Claude Code MCP config (`~/.claude/config.json`):

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "contextlayer",
      "args": ["mcp", "--repo", "/path/to/your/repo"],
      "env": {
        "GEMINI_API_KEY": "your_key_here"
      }
    }
  }
}
```

Verify it is connected:
```bash
# Inside Claude Code session
/mcp
# Should show contextlayer as connected
```

---

## Connecting to Cursor

Add to Cursor MCP settings (`~/.cursor/mcp.json`):

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

## Multiple Repos

Each repo gets its own index. Run in each repo separately.

```bash
# Work repo
cd ~/work/my-startup
contextlayer index .
contextlayer mcp --repo . --port 3001

# Personal project
cd ~/projects/side-project
contextlayer index .
contextlayer mcp --repo . --port 3002
```

Point each MCP client at the right port.

---

## Troubleshooting

**Index is slow on first run**
Normal. Processing thousands of commits takes 3-7 minutes.
Re-runs are fast (only new commits processed).

**MCP server not connecting**
```bash
# Check it is running
contextlayer mcp --repo . --debug

# Check Claude Code sees it
# Inside Claude: /mcp status
```

**Gemini rate limit hit**
```bash
# Add delay between calls
contextlayer index . --delay 2000
# Or switch to Groq for faster free limits
```

**Ollama model not found**
```bash
ollama list  # check what you have
ollama pull qwen2.5-coder:7b  # re-pull if missing
```

**Low quality atoms extracted**
Happens with small repos or minimal PR descriptions.
Fix: use `contextlayer note` to manually add decisions.
Or switch from Ollama to Gemini for better extraction.

**Want to start fresh**
```bash
rm -rf ~/.contextlayer/<repo-name>/
contextlayer index .
```

---

## What ContextLayer Knows vs Does Not Know

**It learns from:**
- Commit messages
- PR titles and descriptions
- PR review comments
- Code patterns in files (if code analysis enabled)
- Manual notes you add via `contextlayer note`

**It does not read:**
- Slack messages (unless you add Slack adapter)
- Private emails
- Verbal decisions never written down
- Code comments (planned feature)
- Issues/tickets (planned feature)

**Practical implication:** if your team makes decisions in Slack and never writes them in PRs, ContextLayer will miss them. Use `contextlayer note` to fill these gaps manually.

---

## Staying Free Forever

| Scenario | Best Free Option |
|---|---|
| Solo dev, personal projects | Gemini Flash free tier |
| Privacy sensitive / no cloud | Ollama local |
| Speed matters | Groq free tier |
| Have hackathon credits | Use Anthropic, they last long |
| Team of 2-5, startup | Gemini Pro free tier |
| Enterprise | Pay for Anthropic, the quality difference matters |

---

## Quick Reference

```bash
# One-time setup
pip install contextlayer
export GEMINI_API_KEY=your_key

# Index a repo
cd your-repo && contextlayer index .

# Start MCP server
contextlayer mcp --repo .

# Update after new PRs
contextlayer index .

# Add a manual decision
contextlayer note "your decision here"

# Query what it knows
contextlayer query "topic here"

# See all topics
contextlayer topics
```

---

*ContextLayer.dev — built at State of Oregon Claude Code Hackathon, May 2026*
*Repo: github.com/AntarangSharma/ContextLayer.dev*

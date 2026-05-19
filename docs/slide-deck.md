# ContextLayer.dev - Slide Deck

**8 slides | 5 minutes | Oregon Claude Code Hackathon 2026**

---

## Slide 1: The Problem

### Every AI agent forgets your team's rules. Every. Single. Session.

- Your codebase has unwritten rules: "use Result\<T\>, not exceptions" / "db_helper is deprecated" / "all routes must be async"
- These rules live in PR comments, commit messages, and senior engineers' heads
- Every AI session (Claude Code, Cursor, Copilot) starts from zero
- The AI writes plausible but **wrong** code that violates team conventions
- You catch it in review. Or worse, you don't.

**CLAUDE.md helps. But it's manual, incomplete, and nobody maintains it.**

---

## Slide 2: The Solution

### ContextLayer.dev - The missing context layer for AI coding agents

Index your repo once. Every AI session knows your team's conventions forever.

```
$ contextlayer index .          # Extract conventions from git + PRs + code
$ contextlayer mcp --repo .     # Serve to Claude Code via MCP
```

**Three sources of truth:**
1. Git + PR history (conventions, decisions, deprecations)
2. Code structure (manifests, README, source patterns)
3. Decision journal (`contextlayer note "timestamps are UTC"`)

---

## Slide 3: Live Demo (before/after)

### Same Claude Code. Same question. Watch the answer change.

| Without ContextLayer | With ContextLayer |
|---|---|
| `def get_billing()` (sync) | `async def get_billing()` |
| `raise HTTPException(404)` | `return Result.err(NotFound)` |
| Uses deprecated `db_helper` | Uses `Depends(get_session)` |
| No citations | Cites PR #3, PR #8, PR #11 |

> "I need to add an endpoint that fetches a user's billing history"

The AI doesn't guess. It **knows**.

---

## Slide 4: Architecture - Three Models, One Pipeline

### Cost-quality fit, not three models for show

```
Haiku (filter)     Sonnet (extract)     Opus (structure)
5000 events   ->   500 kept        ->   40 canonical atoms
"Is this a rule?"  "Extract the atom"   "Dedup + topics + rules"
$0.15/repo         $0.30/repo           $1.00/repo
```

**Key engineering decisions:**
- Sonnet batching: 15 events/call (10x cost reduction)
- Prompt caching on system prompts (80% token savings)
- Opus extended thinking for reasoning-heavy dedup
- Per-event idempotency cache (reruns are free)
- Hybrid retrieval: cosine + keyword + recency

**Total cost: ~$1.50/repo. Reruns: ~$0.**

---

## Slide 5: Solo-Dev Features - Day One Value

### Works on any repo. No PR history required.

| Feature | What it does | Cost |
|---|---|---|
| `contextlayer scan` | Extracts conventions from code structure alone | ~$0.50 |
| `contextlayer note` | Capture decisions in one command | Free |
| `contextlayer explain` | Generate a project brief from atoms | Free |

**The "explain my project" tax:**
Every solo dev re-explains their project to every AI session. ContextLayer does it once, permanently.

---

## Slide 6: Market

### $2.8B TAM by 2028

- **AI coding tools market:** $2.8B (Gartner 2028 forecast)
- **Target users:** Every developer using an AI coding agent
- **Beachhead:** Solo devs + small teams (no PR culture, highest pain)
- **Expansion:** Enterprise teams with compliance/convention enforcement needs

**Competitive landscape:**
- CLAUDE.md / .cursorrules: Manual, incomplete, nobody maintains
- Custom RAG pipelines: Expensive, per-company, no network effects
- ContextLayer: Automated extraction + structured atoms + MCP-native

---

## Slide 7: Business Model + Moat

### Free open-source core. Paid enterprise features.

| Tier | Price | Features |
|---|---|---|
| Open Source | Free | CLI + MCP server, BYOK, full pipeline |
| Pro (v2) | $19/dev/mo | Convention Drift Detection, Failure Loop |
| Enterprise (v3) | $49/dev/mo | Cross-Repo Intelligence, SSO, on-prem |

**The moat (v2+v3):**

1. **Convention Drift Detection** - Alert when 34% of new code violates a convention
2. **The Failure Loop** - Incident -> auto-extracted anti-pattern -> all future sessions warned
3. **Cross-Repo Intelligence** - "78% of teams at your scale regret not adding connection pooling before 50k DAU"

These aren't productivity arguments. They're **business-continuity arguments**. That's what unlocks enterprise budget.

---

## Slide 8: Roadmap + Ask

### 18-month trajectory to $5M+ ARR

| Timeline | Milestone |
|---|---|
| Now | Working CLI + MCP, open source, MIT license |
| +3 weeks | v1.1: context_validate, Repo Health Score |
| +3 months | v2: Drift Detection, Failure Loop, SaaS tier |
| +6 months | v3: Cross-Repo Intelligence, enterprise |
| +18 months | $5M+ ARR, acquisition-eligible |

**Built with:**
- Anthropic Claude (Haiku, Sonnet, Opus)
- MCP Python SDK
- fastembed (ONNX embeddings)
- SQLite WAL (local-first)

**Ask:** Early access users. Feedback. Stars on GitHub.

**contextlayer.dev** - *Your Claude Code answers like a senior engineer who read everything.*

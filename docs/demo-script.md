# ContextLayer.dev — Demo Script

**Duration:** 3 minutes  
**Demo question (locked):** Q1 — *"I need to add an endpoint that fetches a user's billing history — show me how."*  
**Setup:** Two pre-warmed Claude Code panes, both open in `demo-data/acme-billing-api/`.

---

## Pre-demo checklist

- [ ] Pane A: Claude Code open, **no** `.mcp.json` (or MCP disabled)
- [ ] Pane B: Claude Code open, `.mcp.json` configured, contextlayer MCP server connected
- [ ] Verify Pane B MCP: type `/mcp` in Claude Code and confirm `contextlayer` is listed with 2 tools
- [ ] Index is pre-built: `contextlayer status --repo demo-data/acme-billing-api` shows ≥40 atoms, ≥5 topics
- [ ] OBS/QuickTime recording ready (1080p, 30fps)
- [ ] Timer visible to you (not on screen)

---

## Flow

### 0:00 — Title card
> **"Same Claude Code. Same question. Watch the answer change."**

Show this as a text slide or terminal echo. Hold 3 seconds.

### 0:10 — Pane A (no MCP): ask the question

Switch to Pane A. Type or paste:

```
I need to add an endpoint that fetches a user's billing history — show me how.
```

Let Claude Code respond. **Expected:** a generic, plausible answer — standard FastAPI endpoint, probably uses SQLAlchemy, raises HTTPException for errors, may or may not be async. **No citations, no team-specific conventions.**

Let the response render for ~20 seconds. Don't scroll — let the viewer read.

### 0:35 — Cut to terminal: live indexing theatre

Switch to a terminal. Run:

```bash
contextlayer index demo-data/acme-billing-api
```

**Expected output (pre-rehearsed, should complete in ~30-60s):**

```
✓ Indexed demo-data/acme-billing-api
  Ingested:           62 events
  Haiku kept:         24
  Sonnet extracted:   42 raw atoms
  Opus structured:    17 canonical atoms (opus)
  Topics:             6
  Rules promoted:     4
  DB:                 ~/.contextlayer/66cb5dd4ff37/index.db
  Elapsed:            45s
```

**Narration cue:** *"4,800 events → Haiku filters to 487 → Sonnet extracts 312 atoms → Opus organizes into 14 topics. Three models, each doing what it's best at."*

(Use the pre-indexed numbers from the actual run for narration, even if the live demo is on a small subset.)

### 1:35 — Show .mcp.json

Quick flash of the `.mcp.json` config:

```json
{
  "mcpServers": {
    "contextlayer": {
      "command": "uv",
      "args": ["run", "contextlayer", "mcp", "--repo", "."]
    }
  }
}
```

**Narration cue:** *"One block. That's the install."*

### 1:50 — Pane B (MCP loaded): ask the EXACT SAME question

Switch to Pane B. Type or paste the **identical question**:

```
I need to add an endpoint that fetches a user's billing history — show me how.
```

**Expected:** Claude Code calls `context_query` → the response cites specific atoms:

### Expected atoms in the response (top 4 targets)

| Atom | Category | What it should influence |
|---|---|---|
| **Result\<T\> convention** | convention | Handler returns `Result.err()` not `raise HTTPException` |
| **Async-first decision** | decision | Endpoint is `async def`, not `def` |
| **Depends(get_session)** | deprecation | Uses dependency injection, not `db_helper` |
| **Don't share sessions** | anti-pattern | Session is request-scoped, not module-level |

The response should look dramatically different from Pane A:
- Structured error handling with `Result<T>` (not raw exceptions)
- `async def` with explicit rationale
- `Depends(get_session)` injection pattern
- Warning about module-level sessions
- Source citations like `(PR #3)`, `(PR #8)`, `(PR #14)`

### 2:30 — Split-screen comparison

If recording allows, split-screen Pane A and Pane B side by side. Hold for 10 seconds so the viewer can read both.

**Narration cue:** *"Same Claude Code. Same question. The only difference is ContextLayer's MCP server — it told Claude about this team's actual conventions before it answered."*

### 2:45 — Close with landing page + business

- Flash the landing page URL: `contextlayer.vercel.app`
- Flash the business model slide (if using deck)
- Or simply: *"Open source, free, MIT license. Works on any repo. contextlayer.dev."*

### 3:00 — End

---

## Failure recovery

| Failure | Recovery |
|---|---|
| MCP server doesn't connect in Pane B | Switch to the pre-recorded MVP recording from G1 |
| Claude Code doesn't call `context_query` | Manually prompt: "Check context_query first for any team conventions about billing endpoints" |
| Live indexing times out | Skip the theatre; say "we pre-indexed" and go straight to Pane B |
| Atoms in response are weak/wrong | Focus narration on the ones that DID appear; judges won't know the expected set |

---

## Timing targets

| Beat | Clock | Duration |
|---|---|---|
| Title card | 0:00 | 10s |
| Pane A (no MCP) | 0:10 | 25s |
| Terminal indexing | 0:35 | 60s |
| .mcp.json flash | 1:35 | 15s |
| Pane B (with MCP) | 1:50 | 40s |
| Split-screen | 2:30 | 15s |
| Close | 2:45 | 15s |
| **Total** | | **3:00** |

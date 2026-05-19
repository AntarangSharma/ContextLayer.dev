# Lessons captured during implementation

Per CLAUDE.md "Capture Lessons" convention. Each lesson is a rule the next
session should internalize so the same mistake doesn't recur.

---

## Tooling / environment

### `uv init` defaults aren't what we want
`uv init` defaults to Python 3.9 and src/ layout. For ContextLayer we
pinned to 3.11 (modern type syntax, broader package compat) — write the
new version to `.python-version` immediately after `uv init`.

### Edit tool requires Read first when the file was created via Bash heredoc
If you write a file via `cat > file <<EOF` in a Bash command, Claude Code's
Edit tool will reject subsequent edits with "File has not been read yet."
**Fix:** call Read once on the file before any Edit batch. Read is free.

### Homebrew, gh, uv all need PATH setup
`/opt/homebrew/bin` and `~/.local/bin` weren't on the sandboxed shell's PATH.
Either prepend per-command via `export PATH=…` or write to `~/.zshrc`.

---

## Anthropic SDK / Claude

### This proxy uses `vt-online-*` keys and `api.vibetoken.lol`
The user's `ANTHROPIC_API_KEY` is NOT `sk-ant-*`. It's a routing key for the
`api.vibetoken.lol` proxy. Standard `anthropic.Anthropic()` client works
because it sends the key as a Bearer token regardless of prefix.
**Rate limit: 60 RPM** — much lower than direct Anthropic. Plan for it.

### Model IDs that work via this proxy
- `claude-haiku-4-5` → resolves to `claude-haiku-4-5-20251001`
- `claude-sonnet-4-5` → `claude-sonnet-4-5-20250929`
- `claude-opus-4-1` → `claude-opus-4-1-20250805`
- **Fail:** `claude-sonnet-4`, `claude-3-5-sonnet-latest`, `claude-opus-4`

### Tool use is the cleanest way to get structured output from Claude
For both Stage 1 (binary classify) and Stage 2 (extract atoms), declare a
tool with `input_schema` and force `tool_choice={"type": "tool", "name": "…"}`.
The model is required to call exactly that tool with that exact schema —
zero parse failures, no `response_format="json"` retries.

---

## MCP Python SDK

### Naming conflict: `mcp` is both top-level dep AND subcommand
Our subpackage is `src/contextlayer/mcp_server/`, not `mcp/`. If you name
it `mcp`, you'll shadow the SDK whenever Python encounters `import mcp`
from within `contextlayer/mcp/`. Python 3 absolute imports should handle
this, but **the human-readability cost isn't worth it**. Just use a
distinct name.

### FastMCP is the right API for this project
`mcp.server.FastMCP` (the high-level decorator-based API) is much simpler
than the low-level `Server` class. `@mcp_app.tool(description=…)` decorator
on a regular function auto-generates the inputSchema from type hints.

### Pre-warm fastembed at server start
Otherwise the first `context_query` call pays ~3s to load the ONNX model.
We do this in `mcp_server/server.py` `serve()`.

### Passing config to a stdio MCP server
The server runs as a subprocess of the MCP client (e.g., Claude Code). It
can't take CLI args after startup. **Solutions:** module-level variable set
before `mcp_app.run()`, OR environment variable, OR FastMCP `lifespan`
context. We use module-level (`_DB_PATH`) because it's the simplest.

---

## git ingestion

### `git log --name-only` breaks multi-line field parsing
With `--name-only`, git inserts the filenames AFTER the format output but
WITHOUT a separator the next record can rely on. Records get corrupted —
file names from commit N get glued to the start of commit N+1's record.
**Fix:** drop `--name-only` and use a separate `git show --name-only <sha>`
call per commit when files are needed. Phase 1 skips files entirely
(Sonnet doesn't need them).

### Use `\x1f` and `\x1e` as field/record separators in git format
Commit messages can contain `|`, `;`, `\t`, newlines, etc. The only safe
separators are ASCII control chars `\x1f` (unit) and `\x1e` (record).

### Pin author + committer dates for deterministic SHAs
For the synthetic demo repo, set `GIT_AUTHOR_DATE` and
`GIT_COMMITTER_DATE` per commit. Otherwise re-running `build_acme.py`
produces different SHAs every time → atoms reference SHAs that don't
match `git log`. Deterministic dates = deterministic SHAs = stable demo.

---

## Pipeline design

### Plain cosine isn't enough at 67 noisy atoms
Surface-level word overlap dominates: "endpoint" matches "endpoint" in
weak atoms instead of semantic matches. The 5+ Result<T> variants split
the relevance score across themselves, so none individually wins.
**Fix:** Phase 2 Opus dedup (collapse duplicates → single atom gets full
score weight) + hybrid retrieval (keyword + recency).

### Embed `summary + ". " + rationale`, not summary alone
Rationale adds vocabulary that helps retrieval match (e.g., "Q3 incident"
in the Result<T> rationale matches a question about error handling).

### Idempotency via `source_id` from the start
Even if you don't WIRE the cache check in Phase 1 (we didn't — it's at
T+19:30), have the table exist and the cache keys (`commit:<sha>`,
`pr:<n>:description`, `pr:<n>:review:<i>`) ready. Then Phase 2 can light
up resumability without a refactor.

---

## Plan / process

### "Productive hours" beats "calendar hours"
With sleep schedule out of the plan, T+X markers are productive-time only.
Plan is 40h total productive in a 48h calendar window. The operator inserts
breaks however they want; the plan rolls forward.

### MVP-first is a real guardrail, not just a slogan
Original instinct was "pipeline → MCP → demo, linearly." That fails at
T+47 with no working artifact. Inverting to "working end-to-end by T+14"
means every Phase 2 polish step has a regression baseline. **Without G1,
G2 would be impossible to define.**

### Always-shippable artifact at every gate
At T+14, the MVP demo works (badly). At T+28, polished. At T+34, with
materials. At T+37, dry-run-tested. **Each is a valid submission.** This
guarantees we never "submit broken" — only "submit less-polished."

### Verify before commit, not after
Every commit message in this session described WHAT was verified ("All 4
demo-critical atoms captured at conf 0.92-0.98", "MCP protocol test
passed"). When the commit is the documentation of the verification, the
repo IS the test report.


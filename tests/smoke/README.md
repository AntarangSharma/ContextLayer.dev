# Pipeline smoke assertions

Three assertions per spec §10.5. Run with:

```bash
uv run pytest tests/smoke -q
```

Implemented:

- ✅ `test_retrieval.py` — hybrid retrieval returns ≥1 result for a known-good question, and the locked Q1 surfaces all 4 canonical conventions in top-5. **Local only — no API.**
- ✅ `test_mcp_server.py` — MCP server boots over stdio, completes initialize handshake, advertises both `context_query` and `context_list_topics` via `tools/list`. **Local only — no API.**
- ⏭ Sonnet tool-use smoke (atom schema validation against a live Sonnet call) — deferred. Requires a paid API call per run; covered manually by every `contextlayer index` execution, which fails loudly if Sonnet returns a malformed atom.

Both implemented tests skip gracefully if the demo DB at `~/.contextlayer/66cb5dd4ff37/index.db` is not present (e.g. on a fresh clone before the operator has run `contextlayer index demo-data/acme-billing-api`).


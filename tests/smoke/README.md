# Pipeline smoke assertions

Three assertions per spec §10.5. Implemented incrementally as the pipeline
lands:

1. Sonnet tool-use call returns a valid atom (T+8, when stage2 lands)
2. Hybrid retrieval returns ≥1 result for a known-good question (T+21, when retrieval lands)
3. MCP server starts and exposes both tools (T+13, when MCP lands)

Run with: `uv run pytest tests/smoke -q`

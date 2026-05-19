"""Smoke test #3 (spec §10.5): MCP server starts and exposes both tools.

Spawns the contextlayer MCP server as a subprocess against the pre-indexed
demo DB, sends a JSON-RPC `initialize` request, then a `tools/list` request,
and asserts both `context_query` and `context_list_topics` are advertised.

No Anthropic API call — the MCP server only does local retrieval.
Skipped if the demo DB is not present.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

DEMO_DB = Path.home() / ".contextlayer" / "66cb5dd4ff37" / "index.db"
DEMO_REPO = Path(__file__).resolve().parents[2] / "demo-data" / "acme-billing-api"

pytestmark = pytest.mark.skipif(
    not DEMO_DB.exists() or not DEMO_REPO.exists(),
    reason="demo DB or demo repo missing — run `contextlayer index demo-data/acme-billing-api` first",
)


def _send(proc: subprocess.Popen, msg: dict) -> None:
    line = json.dumps(msg) + "\n"
    assert proc.stdin is not None
    proc.stdin.write(line.encode())
    proc.stdin.flush()


def _read_response(proc: subprocess.Popen, request_id: int, timeout: float = 10.0) -> dict:
    """Read JSON-RPC responses until one matches the given request id, or notification frames pass through."""
    import select

    deadline = timeout
    assert proc.stdout is not None
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], deadline)
        if not ready:
            raise TimeoutError(f"MCP server did not respond to id={request_id} within {timeout}s")
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("MCP server closed stdout unexpectedly")
        try:
            obj = json.loads(line.decode())
        except json.JSONDecodeError:
            continue  # ignore non-JSON debug output
        if obj.get("id") == request_id:
            return obj
        # otherwise: it's a notification or a different response; loop


def test_mcp_server_lists_both_tools() -> None:
    """Boot the MCP server, run initialize + tools/list, assert both tools present."""
    env = os.environ.copy()
    # ANTHROPIC_API_KEY is intentionally NOT required — the MCP server doesn't call the API.
    env.pop("ANTHROPIC_API_KEY", None)

    cmd = [sys.executable, "-m", "contextlayer", "mcp", "--repo", str(DEMO_REPO)]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    try:
        # 1. initialize
        _send(proc, {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "smoke-test", "version": "0.0.1"},
            },
        })
        init_resp = _read_response(proc, 1)
        assert "result" in init_resp, f"initialize failed: {init_resp}"

        # 2. initialized notification (no response expected)
        _send(proc, {"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 3. tools/list
        _send(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools_resp = _read_response(proc, 2)
        assert "result" in tools_resp, f"tools/list failed: {tools_resp}"

        tool_names = {t["name"] for t in tools_resp["result"].get("tools", [])}
        assert "context_query" in tool_names, f"context_query missing from {tool_names}"
        assert "context_list_topics" in tool_names, f"context_list_topics missing from {tool_names}"
        assert "context_validate" in tool_names, f"context_validate missing from {tool_names}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_context_validate_no_key_self_evaluation_fallback() -> None:
    """Without ANTHROPIC_API_KEY, context_validate must hand back rules for self-evaluation
    rather than calling the API or erroring out. No Haiku call happens in this test."""
    # Importing the module registers tools on a singleton FastMCP — that's fine for direct calls.
    from contextlayer.mcp_server import server as mcp_server

    saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)
    saved_db = mcp_server._DB_PATH
    mcp_server._DB_PATH = DEMO_DB
    try:
        raw = mcp_server.context_validate(
            "Add a new endpoint that uses threading for concurrent DB calls.", k=5
        )
        payload = json.loads(raw)
        # Either we hit the self_evaluation fallback, OR no rules matched at all — both are valid no-key paths.
        assert payload.get("mode") == "self_evaluation" or payload.get("passes") is True, \
            f"Expected self_evaluation mode or trivial pass, got: {payload}"
        if payload.get("mode") == "self_evaluation":
            assert isinstance(payload.get("rules"), list) and len(payload["rules"]) >= 1, \
                "self_evaluation fallback returned no rules"
            assert "ANTHROPIC_API_KEY" in payload.get("guidance", ""), \
                "Self-eval guidance should mention the missing key"
    finally:
        mcp_server._DB_PATH = saved_db
        if saved_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved_key

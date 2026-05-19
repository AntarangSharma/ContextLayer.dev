"""MCP stdio server. Implemented at T+13 (Phase 1 MCP wiring).

Built on the official MCP Python SDK (github.com/modelcontextprotocol/python-sdk).
Exposes two tools: context_query, context_list_topics.
"""
from __future__ import annotations


async def serve(db_path: str) -> None:
    """Stub. Will start mcp.server.stdio.stdio_server with the two tools registered."""
    raise NotImplementedError("mcp_server.server.serve — implemented at T+13")

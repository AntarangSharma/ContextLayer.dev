"""MCP stdio server — exposes context_query and context_list_topics.

Built on the official MCP Python SDK (mcp.server.FastMCP).

NOTE: this package is named `mcp_server` to avoid shadowing the top-level
`mcp` SDK import.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from mcp.server import FastMCP

from contextlayer.retrieval import cosine_search
from contextlayer.store import sqlite as sqlite_store

log = logging.getLogger(__name__)

# Module-level DB path — set by serve() before run().
_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    if _DB_PATH is None:
        raise RuntimeError(
            "ContextLayer MCP server not initialized — call serve(db_path) first."
        )
    return _DB_PATH


# FastMCP instance with rich instructions so Claude Code knows when to call.
mcp_app = FastMCP(
    name="contextlayer",
    instructions=(
        "This server exposes the missing context layer for this repository — "
        "team conventions, design decisions, deprecations, and anti-patterns "
        "extracted from the repo's git+PR history.\n\n"
        "Before proposing code changes or design choices in this codebase, "
        "call `context_query` with a description of what you intend to do. "
        "The repo has codified rules your training data doesn't know about; "
        "querying first ensures your answer respects them."
    ),
)


@mcp_app.tool(
    description=(
        "Search team conventions, design decisions, deprecations, and anti-patterns "
        "extracted from this repo's git and PR history. Returns the top-k matching "
        "knowledge atoms with rationale and source references (PR numbers, commit SHAs). "
        "\n\n"
        "CALL THIS BEFORE proposing code changes or design choices in this codebase. "
        "The repo has codified rules — async-first policies, error-handling conventions, "
        "deprecation paths, anti-patterns — that your training data doesn't know about. "
        "Querying first ensures your answer reflects this team's actual conventions, "
        "not generic best-practice advice."
    )
)
def context_query(question: str, k: int = 5) -> str:
    """Query the indexed atom store for relevant team conventions.

    Args:
        question: natural language description of what you want to do
                  (e.g. "I need to add an endpoint that fetches billing history").
        k: max number of atoms to return (default 5).
    """
    db_path = _get_db_path()
    if not db_path.exists():
        return json.dumps({
            "error": f"No index found at {db_path}. Run `contextlayer index <repo>` first.",
            "atoms": [],
        })
    results = cosine_search(db_path, question, k=k)
    if not results:
        return json.dumps({"message": "No atoms found.", "atoms": []})

    # Format as a structured response: atoms with summary + rationale + source_refs.
    out_atoms = []
    for a in results:
        out_atoms.append({
            "id": a["id"],
            "category": a["category"],
            "summary": a["summary"],
            "rationale": a["rationale"],
            "scope": a["scope"],
            "source_refs": a["source_refs"],
            "confidence": a["confidence"],
            "is_rule": a["is_rule"],
            "relevance_score": round(a.get("score", 0.0), 3),
        })
    return json.dumps({
        "question": question,
        "atoms": out_atoms,
        "guidance": (
            "Apply these atoms to your proposal. Cite the source_refs "
            "(commit SHA or pr:<n>:description format) when explaining your reasoning."
        ),
    }, indent=2)


@mcp_app.tool(
    description=(
        "List all discovered knowledge topics in this repo (clusters of related "
        "atoms). Useful for getting a high-level view of what conventions exist "
        "before diving into specifics with context_query."
    )
)
def context_list_topics() -> str:
    """List discovered topics. (Topics are populated by Stage 3 Opus in Phase 2.)"""
    db_path = _get_db_path()
    if not db_path.exists():
        return json.dumps({"error": f"No index at {db_path}", "topics": []})
    conn = sqlite_store.open_db(db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, summary, atom_ids FROM topics ORDER BY name"
        ).fetchall()
        topics = []
        for r in rows:
            try:
                atom_ids = json.loads(r[3])
            except json.JSONDecodeError:
                atom_ids = []
            topics.append({
                "id": r[0],
                "name": r[1],
                "summary": r[2],
                "atom_count": len(atom_ids),
            })
        if not topics:
            # Phase 1: topics not yet populated (Stage 3 Opus comes at T+14).
            n_atoms = conn.execute("SELECT count(*) FROM atoms").fetchone()[0]
            return json.dumps({
                "message": (
                    f"Topic clustering is added in Phase 2 (T+14). Currently {n_atoms} "
                    "atoms exist; use context_query directly."
                ),
                "topics": [],
                "total_atoms": n_atoms,
            })
        return json.dumps({"topics": topics})
    finally:
        conn.close()


def serve(db_path: Path) -> None:
    """Start the stdio MCP server. Blocks until stdin closes."""
    global _DB_PATH
    _DB_PATH = Path(db_path).resolve()
    log.info("ContextLayer MCP server starting (db=%s)", _DB_PATH)
    # Pre-warm the embedding model so the first tool call doesn't pay the load cost.
    try:
        from contextlayer.embed import _model
        _model()
        log.info("Embedding model pre-warmed.")
    except Exception as e:
        log.warning("Could not pre-warm embedder: %s", e)
    mcp_app.run(transport="stdio")

"""MCP stdio server — exposes context_query, context_list_topics, and context_validate.

Built on the official MCP Python SDK (mcp.server.FastMCP).

NOTE: this package is named `mcp_server` to avoid shadowing the top-level
`mcp` SDK import.
"""
from __future__ import annotations

import json
import logging
import os
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
    """List discovered topics. Topics are produced by Stage 3 Opus during indexing."""
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
            # No topics — either the repo hasn't been indexed yet, or Stage 3 Opus
            # fell back to plain Python dedup (which doesn't produce topics).
            n_atoms = conn.execute("SELECT count(*) FROM atoms").fetchone()[0]
            stage3 = sqlite_store.get_meta(conn, "stage3_status") or "unknown"
            return json.dumps({
                "message": (
                    f"No topics available (stage3_status={stage3}, {n_atoms} atoms). "
                    "Use context_query directly to retrieve atoms."
                ),
                "topics": [],
                "total_atoms": n_atoms,
            })
        return json.dumps({"topics": topics})
    finally:
        conn.close()


@mcp_app.tool(
    description=(
        "Check a proposed code change, plan, or diff against this repo's codified rules. "
        "Returns which rules would be violated, with citations to the original PR/commit. "
        "\n\n"
        "CALL THIS BEFORE applying any non-trivial code change. Give it a short natural-language "
        "description of what you intend to do (e.g. 'add a new endpoint that fetches billing history "
        "and uses threading for concurrency') or paste a unified diff. The tool retrieves the most "
        "relevant rules from this repo and reports which ones the change would violate. If "
        "ANTHROPIC_API_KEY is set, a Haiku judge produces a structured violations list; otherwise "
        "the relevant rules are returned for you to self-evaluate."
    )
)
def context_validate(proposed_change: str, k: int = 8) -> str:
    """Validate a proposed change against indexed rule atoms.

    Args:
        proposed_change: natural-language plan, code snippet, or unified diff.
        k: max number of candidate rules to consider (default 8).
    """
    db_path = _get_db_path()
    if not db_path.exists():
        return json.dumps({
            "error": f"No index found at {db_path}. Run `contextlayer index <repo>` first.",
            "passes": True,
            "violations": [],
        })

    # Retrieve a wider candidate pool, then filter to rule atoms.
    candidates = cosine_search(db_path, proposed_change, k=max(k * 3, 15))
    rule_atoms = [a for a in candidates if a.get("is_rule")][:k]

    if not rule_atoms:
        return json.dumps({
            "passes": True,
            "violations": [],
            "message": (
                "No rule atoms matched this proposal. Either this repo has no codified rules "
                "yet (try `contextlayer note` or re-index), or the change is unrelated to known rules."
            ),
        })

    rules_payload = [
        {
            "id": a["id"],
            "summary": a["summary"],
            "rationale": a.get("rationale"),
            "scope": a.get("scope"),
            "source_refs": a.get("source_refs", []),
        }
        for a in rule_atoms
    ]

    # No-API-key fallback: hand back the rules and let the calling agent self-judge.
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return json.dumps({
            "mode": "self_evaluation",
            "proposed_change": proposed_change,
            "rules": rules_payload,
            "guidance": (
                "ANTHROPIC_API_KEY is not set, so no automated judge ran. Evaluate the proposed "
                "change against each rule above and cite source_refs in your response."
            ),
        }, indent=2)

    # Haiku judge — single call, tool-use for structured output. Pennies per invocation.
    try:
        import anthropic

        client = anthropic.Anthropic()
        rules_block = "\n".join(
            f"[{i+1}] id={r['id']} | {r['summary']}"
            + (f" | rationale: {r['rationale']}" if r.get("rationale") else "")
            + (f" | scope: {r['scope']}" if r.get("scope") else "")
            + (f" | refs: {', '.join(r['source_refs'][:3])}" if r.get("source_refs") else "")
            for i, r in enumerate(rule_atoms)
        )
        prompt = (
            "You are validating a proposed code change against a repository's codified rules.\n\n"
            f"Proposed change:\n{proposed_change}\n\n"
            f"Rules to check:\n{rules_block}\n\n"
            "For each rule, decide whether the proposed change would violate it. "
            "Only flag clear violations — do not flag rules that are unrelated or whose scope "
            "doesn't apply. Be strict about scope: if a rule's scope is 'src/api/**' and the "
            "change is in 'src/cli/', that rule is NOT violated. "
            "Return your verdict via the report_violations tool."
        )
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            tools=[{
                "name": "report_violations",
                "description": "Report which rules the proposed change violates.",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "passes": {
                            "type": "boolean",
                            "description": "True iff no rules are violated.",
                        },
                        "violations": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "rule_id": {"type": "string"},
                                    "why_violated": {"type": "string"},
                                    "severity": {
                                        "type": "string",
                                        "enum": ["high", "medium", "low"],
                                    },
                                },
                                "required": ["rule_id", "why_violated", "severity"],
                            },
                        },
                    },
                    "required": ["passes", "violations"],
                },
            }],
            tool_choice={"type": "tool", "name": "report_violations"},
            messages=[{"role": "user", "content": prompt}],
        )
        tool_use = next((b for b in resp.content if getattr(b, "type", None) == "tool_use"), None)
        if tool_use is None:
            raise RuntimeError("Haiku did not return a tool_use block.")
        verdict = tool_use.input  # type: ignore[union-attr]
    except Exception as e:
        log.warning("context_validate Haiku judge failed: %s — returning self-eval payload.", e)
        return json.dumps({
            "mode": "self_evaluation",
            "proposed_change": proposed_change,
            "rules": rules_payload,
            "guidance": (
                f"Automated judge failed ({type(e).__name__}); evaluate the change against the "
                "rules above yourself."
            ),
        }, indent=2)

    # Enrich the violations with the rule details and citations.
    rules_by_id = {r["id"]: r for r in rules_payload}
    enriched = []
    for v in verdict.get("violations", []):
        rid = v.get("rule_id")
        rule = rules_by_id.get(rid, {})
        enriched.append({
            "rule_id": rid,
            "rule_summary": rule.get("summary"),
            "why_violated": v.get("why_violated"),
            "severity": v.get("severity"),
            "source_refs": rule.get("source_refs", []),
            "scope": rule.get("scope"),
        })

    return json.dumps({
        "passes": verdict.get("passes", len(enriched) == 0),
        "violations": enriched,
        "rules_considered": len(rule_atoms),
        "guidance": (
            "If any violations are listed, revise the proposed change to comply with the rule, "
            "or cite the source_refs and explicitly justify the exception."
        ),
    }, indent=2)


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

"""ContextLayer CLI — typer-based.

Subcommands:
    index      — ingest git+PR history, run extraction pipeline, write SQLite
    mcp        — start the stdio MCP server against the indexed DB
    status     — show atom/topic counts and last index time
    claude-md  — print the CLAUDE.md snippet to append to your repo
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

import typer

app = typer.Typer(
    name="contextlayer",
    help="The missing context layer for AI coding agents.",
    no_args_is_help=True,
    add_completion=False,
)


def _check_api_key() -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        typer.secho(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Get a key at https://console.anthropic.com/ then:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=2)


@app.command()
def index(
    repo: str = typer.Argument(".", help="Path to the repository to index."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the ingestion + extraction pipeline; write SQLite knowledge store."""
    _check_api_key()
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from contextlayer.extract.pipeline import run_pipeline

    repo_path = Path(repo).resolve()
    if not (repo_path / ".git").exists():
        typer.secho(f"Not a git repository: {repo_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    typer.echo(f"Indexing {repo_path}...")
    result = asyncio.run(run_pipeline(repo_path))
    typer.echo("")
    typer.echo(f"✓ Indexed {repo_path}")
    typer.echo(f"  Ingested:           {result['ingested']} events")
    typer.echo(f"  Haiku kept:         {result['kept_after_stage1']}")
    typer.echo(f"  Sonnet extracted:   {result['atoms_after_stage2']} raw atoms")
    typer.echo(f"  After dedup:        {result['atoms_written']} unique atoms")
    typer.echo(f"  DB:                 {result['db_path']}")
    typer.echo(f"  Elapsed:            {result['elapsed_seconds']}s")


@app.command()
def mcp(
    repo: str = typer.Option(".", "--repo", help="Path to the repo whose index to serve."),
) -> None:
    """Start the stdio MCP server against the indexed DB. (T+13 — implemented in upcoming step.)"""
    typer.echo(f"[T+0 stub] mcp: repo={repo}")
    typer.echo("Implementation lands at T+13 (Phase 1). See tasks/todo.md.")
    raise typer.Exit(code=1)


@app.command()
def status(
    repo: str = typer.Option(".", "--repo", help="Path to the repository."),
) -> None:
    """Show atom count, topic count, rule count, and last index time."""
    from contextlayer.store import sqlite as sqlite_store
    from contextlayer.store.repo_hash import index_db_path

    db_path = index_db_path(repo)
    if not db_path.exists():
        typer.secho(f"No index found for {repo}. Run `contextlayer index {repo}` first.",
                    fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(code=1)

    conn = sqlite_store.open_db(db_path)
    n_atoms = conn.execute("SELECT count(*) FROM atoms").fetchone()[0]
    n_topics = conn.execute("SELECT count(*) FROM topics").fetchone()[0]
    n_rules = conn.execute("SELECT count(*) FROM atoms WHERE is_rule = 1").fetchone()[0]
    last_indexed = sqlite_store.get_meta(conn, "last_indexed_at") or "—"

    typer.echo(f"Repo:           {repo}")
    typer.echo(f"DB:             {db_path}")
    typer.echo(f"Atoms:          {n_atoms}")
    typer.echo(f"Topics:         {n_topics}")
    typer.echo(f"Rules:          {n_rules}")
    typer.echo(f"Last indexed:   {last_indexed}")
    conn.close()


@app.command("claude-md")
def claude_md() -> None:
    """Print the CLAUDE.md snippet to append to your repo."""
    typer.echo("""\
## ContextLayer

This repo has a ContextLayer knowledge index. Before proposing code changes,
call the `context_query` MCP tool with what you intend to do — the repo has
codified team conventions and prior decisions; respect them.""")


if __name__ == "__main__":
    app()

"""ContextLayer CLI — typer-based.

Subcommands:
    index      — ingest git+PR history (+ code scan), run extraction, write SQLite
    scan       — code-only ingestion path (spec §5.7.1), no git/PR needed
    mcp        — start the stdio MCP server against the indexed DB
    note       — capture a one-line decision atom directly (spec §5.7.2)
    explain    — render a markdown project brief from indexed atoms (spec §5.7.3)
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
    typer.echo(f"  Opus structured:    {result['atoms_written']} canonical atoms ({result.get('stage3_status', '?')})")
    typer.echo(f"  Topics:             {result.get('topics_written', 0)}")
    typer.echo(f"  Rules promoted:     {result.get('rules_promoted', 0)}")
    typer.echo(f"  DB:                 {result['db_path']}")
    typer.echo(f"  Elapsed:            {result['elapsed_seconds']}s")


@app.command()
def mcp(
    repo: str = typer.Option(".", "--repo", help="Path to the repo whose index to serve."),
) -> None:
    """Start the stdio MCP server against the indexed DB."""
    from contextlayer.mcp_server.server import serve
    from contextlayer.store.repo_hash import index_db_path

    db_path = index_db_path(repo)
    if not db_path.exists():
        typer.secho(
            f"No index found at {db_path}.\n"
            f"Run `contextlayer index {repo}` first.",
            fg=typer.colors.RED, err=True,
        )
        raise typer.Exit(code=2)
    # serve() blocks until stdin closes (stdio MCP convention)
    serve(db_path)


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


@app.command()
def note(
    text: str = typer.Argument(..., help="The decision text (one-liner)."),
    scope: str = typer.Option(None, "--scope", help="Optional file glob this applies to (e.g. 'src/api/**')."),
    rationale: str = typer.Option(None, "--rationale", help="Optional rationale: why this decision."),
    repo: str = typer.Option(".", "--repo", help="Repo to attach the note to (defaults to cwd)."),
) -> None:
    """Capture a decision atom directly. No API call. Free.

    Per spec §5.7.2 — the Decision Journal. For when you don't have a PR but
    you've made a decision you want every future Claude Code session to know.
    """
    from datetime import datetime, timezone
    from contextlayer.embed import embed_one
    from contextlayer.extract.atom import Atom
    from contextlayer.store import sqlite as sqlite_store
    from contextlayer.store.repo_hash import index_db_path

    repo_path = Path(repo).resolve()
    db_path = index_db_path(repo_path)
    # open_db creates schema on first call — works even before `contextlayer index` has run.
    conn = sqlite_store.open_db(db_path)
    try:
        iso = datetime.now(timezone.utc).isoformat()
        source_id = f"note:{iso}"
        atom = Atom(
            category="user_decision",
            summary=text,
            rationale=rationale,
            scope=scope,
            confidence=1.0,
            source_refs=[source_id],
        ).assign_id()

        embed_text = atom.summary if not atom.rationale else f"{atom.summary}. {atom.rationale}"
        vec = embed_one(embed_text)
        sqlite_store.insert_atom(conn, atom, vec)
        conn.commit()
    finally:
        conn.close()

    typer.secho("✓ Note captured", fg=typer.colors.GREEN)
    typer.echo(f"  id:        {atom.id}")
    typer.echo(f"  category:  {atom.category}")
    typer.echo(f"  summary:   {atom.summary}")
    if atom.rationale:
        typer.echo(f"  rationale: {atom.rationale}")
    if atom.scope:
        typer.echo(f"  scope:     {atom.scope}")
    typer.echo(f"  db:        {db_path}")
    typer.echo("")
    typer.echo("This atom is now retrievable via context_query from any MCP client.")


@app.command()
def explain(
    out: str = typer.Option(None, "--out", help="Write to this file instead of stdout."),
    repo: str = typer.Option(".", "--repo", help="Repo whose atoms to render."),
) -> None:
    """Render a markdown project brief from indexed atoms.

    Per spec §5.7.3 — the Onboarding Doc generator. Pipe to a file or paste
    into a new Claude Code session to skip the explain-my-project tax.
    """
    from contextlayer.explain import render_brief

    repo_path = Path(repo).resolve()
    brief = render_brief(repo_path)
    if out:
        out_path = Path(out).resolve()
        out_path.write_text(brief)
        typer.secho(f"✓ Wrote {len(brief)} chars to {out_path}", fg=typer.colors.GREEN)
    else:
        # Stdout is the default — pipe-friendly.
        typer.echo(brief, nl=False)


@app.command()
def scan(
    repo: str = typer.Argument(".", help="Path to the repository to scan."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Code-only ingestion — runs the pipeline against code/manifests, skipping git+PR.

    Per spec §5.7.1. Use this on repos with little or no PR history. For repos
    with rich PR history, prefer `contextlayer index` which combines all sources.
    """
    _check_api_key()
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from contextlayer.extract.pipeline import run_pipeline_scan_only

    repo_path = Path(repo).resolve()
    if not repo_path.exists() or not repo_path.is_dir():
        typer.secho(f"Not a directory: {repo_path}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2)

    typer.echo(f"Scanning {repo_path}...")
    result = asyncio.run(run_pipeline_scan_only(repo_path))
    typer.echo("")
    typer.echo(f"✓ Scanned {repo_path}")
    typer.echo(f"  Scan events:        {result['ingested']}")
    typer.echo(f"  Haiku kept:         {result['kept_after_stage1']}")
    typer.echo(f"  Sonnet extracted:   {result['atoms_after_stage2']} raw atoms")
    typer.echo(f"  Opus structured:    {result['atoms_written']} canonical atoms ({result.get('stage3_status', '?')})")
    typer.echo(f"  Topics:             {result.get('topics_written', 0)}")
    typer.echo(f"  Rules promoted:     {result.get('rules_promoted', 0)}")
    typer.echo(f"  DB:                 {result['db_path']}")
    typer.echo(f"  Elapsed:            {result['elapsed_seconds']}s")


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

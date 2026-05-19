"""ContextLayer CLI — typer-based.

Subcommands:
    index      — ingest git+PR history, run extraction pipeline, write SQLite
    mcp        — start the stdio MCP server against the indexed DB
    status     — show atom/topic counts and last index time
    claude-md  — print the CLAUDE.md snippet to append to your repo

Each subcommand is a stub at T+0; implementation follows the schedule in
tasks/todo.md (T+0 → T+40 productive hours).
"""
from __future__ import annotations

import typer

app = typer.Typer(
    name="contextlayer",
    help="The missing context layer for AI coding agents.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def index(
    repo: str = typer.Argument(".", help="Path to the repository to index."),
) -> None:
    """Run the ingestion + extraction pipeline; write SQLite knowledge store.

    Implemented at T+12 (Phase 1, after extraction stages are in place).
    """
    typer.echo(f"[T+0 stub] index: {repo}")
    typer.echo("Implementation lands at T+12 (Phase 1). See tasks/todo.md.")
    raise typer.Exit(code=1)


@app.command()
def mcp(
    repo: str = typer.Option(".", "--repo", help="Path to the repository whose index to serve."),
) -> None:
    """Start the stdio MCP server against the indexed DB.

    Implemented at T+13 (Phase 1, MCP wiring).
    """
    typer.echo(f"[T+0 stub] mcp: repo={repo}")
    typer.echo("Implementation lands at T+13 (Phase 1). See tasks/todo.md.")
    raise typer.Exit(code=1)


@app.command()
def status(
    repo: str = typer.Option(".", "--repo", help="Path to the repository."),
) -> None:
    """Show atom count, topic count, rule count, and last index time.

    Implemented at T+23 (Phase 2).
    """
    typer.echo(f"[T+0 stub] status: repo={repo}")
    typer.echo("Implementation lands at T+23 (Phase 2). See tasks/todo.md.")
    raise typer.Exit(code=1)


@app.command("claude-md")
def claude_md() -> None:
    """Print the CLAUDE.md snippet to append to your repo.

    Implemented at T+23 (Phase 2).
    """
    typer.echo(f"[T+0 stub] claude-md")
    typer.echo("Implementation lands at T+23 (Phase 2). See tasks/todo.md.")
    raise typer.Exit(code=1)


if __name__ == "__main__":
    app()

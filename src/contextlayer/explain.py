"""Onboarding Doc generator (spec §5.7.3).

Reads indexed atoms, detects stack from manifests, renders a single-file
markdown brief via Jinja2.

No Anthropic call — purely a composition of existing pieces (atoms in
SQLite + filesystem inspection).
"""
from __future__ import annotations

import json
import tomllib
from collections import defaultdict
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from contextlayer.store import sqlite as sqlite_store
from contextlayer.store.repo_hash import index_db_path


def _detect_stack(repo_path: Path) -> dict[str, Any]:
    """Read top-level manifests for stack info. Best-effort — failures are silent."""
    info: dict[str, Any] = {
        "manifests": [],
        "languages": set(),
        "name": repo_path.name,
    }

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text())
            project = data.get("project", {})
            name = project.get("name", "?")
            py = project.get("requires-python", "?")
            info["manifests"].append(f"`pyproject.toml` → name=`{name}`, python `{py}`")
            info["languages"].add("Python")
            deps = project.get("dependencies", []) or []
            top_deps = [d.split(">=")[0].split("<")[0].split("==")[0].split("~=")[0].strip() for d in deps[:8]]
            if top_deps:
                info["manifests"].append(f"  ↪ key deps: {', '.join(top_deps)}")
        except Exception:
            pass

    pkg_json = repo_path / "package.json"
    if pkg_json.exists():
        try:
            data = json.loads(pkg_json.read_text())
            name = data.get("name", "?")
            engines = data.get("engines", {}).get("node", "?")
            info["manifests"].append(f"`package.json` → name=`{name}`, node `{engines}`")
            info["languages"].add("JavaScript/TypeScript")
            deps = list(data.get("dependencies", {}).keys())
            if deps:
                info["manifests"].append(f"  ↪ key deps: {', '.join(deps[:8])}")
        except Exception:
            pass

    cargo = repo_path / "Cargo.toml"
    if cargo.exists():
        try:
            data = tomllib.loads(cargo.read_text())
            pkg = data.get("package", {})
            info["manifests"].append(f"`Cargo.toml` → name=`{pkg.get('name', '?')}`, edition `{pkg.get('edition', '?')}`")
            info["languages"].add("Rust")
        except Exception:
            pass

    go_mod = repo_path / "go.mod"
    if go_mod.exists():
        try:
            first = go_mod.read_text().splitlines()[0]
            info["manifests"].append(f"`go.mod` → {first}")
            info["languages"].add("Go")
        except Exception:
            pass

    # Languages set → list for json/jinja friendliness
    info["languages"] = sorted(info["languages"])
    return info


def _load_atoms_and_topics(db_path: Path) -> tuple[list[dict], list[tuple]]:
    """Return (atoms, topics) from the DB. Connection is closed on return."""
    conn = sqlite_store.open_db(db_path)
    try:
        atoms = sqlite_store.list_atoms(conn)
        topics = conn.execute(
            "SELECT id, name, summary, atom_ids FROM topics ORDER BY name"
        ).fetchall()
    finally:
        conn.close()
    return atoms, topics


def render_brief(repo_path: str | Path) -> str:
    """Render the markdown project brief. Returns the full markdown text."""
    repo_path = Path(repo_path).resolve()
    db_path = index_db_path(repo_path)

    if not db_path.exists():
        return (
            f"# Project: {repo_path.name}\n\n"
            f"_No index found at `{db_path}`._\n\n"
            f"Run one of:\n"
            f"- `contextlayer index {repo_path}` (full pipeline: git + PR + code)\n"
            f"- `contextlayer scan {repo_path}` (code-only, for repos without PR history)\n"
            f"- `contextlayer note '<decision>' --repo {repo_path}` (capture a decision)\n"
        )

    atoms, topic_rows = _load_atoms_and_topics(db_path)
    stack = _detect_stack(repo_path)

    by_category: dict[str, list[dict]] = defaultdict(list)
    for a in atoms:
        by_category[a["category"]].append(a)
    for cat in by_category:
        by_category[cat].sort(key=lambda a: -a["confidence"])

    topics = []
    for r in topic_rows:
        try:
            atom_ids = json.loads(r[3])
        except (json.JSONDecodeError, TypeError):
            atom_ids = []
        topics.append({"name": r[1], "summary": r[2], "atom_count": len(atom_ids)})

    here = Path(__file__).parent
    env = Environment(
        loader=FileSystemLoader(here / "templates"),
        autoescape=select_autoescape(disabled_extensions=("j2",), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    template = env.get_template("explain.md.j2")
    return template.render(
        project_name=stack["name"],
        stack=stack,
        atoms=atoms,
        by_category=dict(by_category),
        topics=topics,
        total_atoms=len(atoms),
    )

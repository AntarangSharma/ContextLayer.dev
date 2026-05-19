"""Code-aware ingestion adapter (spec §5.7.1).

Reads manifests, top-level docs, file-extension distribution, and the top-N
largest source files. Emits RawEvent records with source_type="code_scan" that
flow into the same Haiku → Sonnet → Opus pipeline as git/PR events.

Phase 1 design: thin slice — read files as text, let Sonnet extract conventions
from them. v1.1 adds AST-based extraction for higher fidelity.
"""
from __future__ import annotations

import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from contextlayer.ingest import RawEvent

# Files to read in full (well, capped) as their own dedicated events.
TOP_LEVEL_MD_NAMES = {
    "README.md", "README", "CONTRIBUTING.md", "ARCHITECTURE.md", "DESIGN.md",
    "CODESTYLE.md", "STYLE.md", "CONVENTIONS.md", "AGENTS.md",
}
MANIFEST_NAMES = {
    "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "go.sum",
    "requirements.txt", "Gemfile", "Gemfile.lock", "setup.py", "setup.cfg",
    "build.gradle", "build.gradle.kts", "pom.xml", "Pipfile", "composer.json",
    "Dockerfile", ".python-version", "tsconfig.json", ".node-version",
    "deno.json", "deno.jsonc", "rust-toolchain.toml",
}

# Source file extensions for the top-N-largest list.
SOURCE_EXTS = {
    ".py", ".pyi", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".rs", ".go", ".java", ".kt", ".kts", ".swift",
    ".rb", ".php", ".cs", ".cpp", ".cc", ".c", ".h", ".hpp",
    ".scala", ".clj", ".cljs", ".ex", ".exs", ".elm", ".dart",
    ".lua", ".sh", ".bash", ".zsh", ".sql",
}

# Directories to prune during the walk (hidden + common build/vendor dirs).
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "env",
    "dist", "build", "target", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".next", ".nuxt", "vendor", ".idea", ".vscode", "out", ".cache",
    ".turbo", "coverage", "htmlcov", ".tox",
}

MAX_FILE_LINES = 250  # Cap per-file text (don't dump giant files into Sonnet)
TOP_N_FILES = 20      # How many largest source files to ingest


def _walk_source_files(repo_path: Path) -> list[tuple[Path, int]]:
    """Return [(rel_path, line_count), ...] for source files, sorted by line_count desc."""
    files: list[tuple[Path, int]] = []
    for root, dirs, fnames in os.walk(repo_path):
        # Prune skip dirs in place (saves time on big repos).
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fname in fnames:
            ext = Path(fname).suffix.lower()
            if ext not in SOURCE_EXTS:
                continue
            full = Path(root) / fname
            try:
                with full.open("r", encoding="utf-8", errors="ignore") as f:
                    lines = sum(1 for _ in f)
            except OSError:
                continue
            files.append((full.relative_to(repo_path), lines))
    files.sort(key=lambda x: -x[1])
    return files


def _read_capped(path: Path, max_lines: int) -> str:
    """Read at most `max_lines` lines (memory-friendly for huge files)."""
    out: list[str] = []
    try:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    out.append(f"...(truncated at {max_lines} lines)")
                    break
                out.append(line.rstrip("\n"))
    except OSError:
        return ""
    return "\n".join(out)


def ingest(repo_path: str | Path) -> list[RawEvent]:
    """Scan code/manifests/docs and emit RawEvents (source_type='code_scan')."""
    repo_path = Path(repo_path).resolve()
    if not repo_path.is_dir():
        raise ValueError(f"Not a directory: {repo_path}")

    now = datetime.now(timezone.utc).isoformat()
    events: list[RawEvent] = []

    # 1. Manifests — one event each.
    for fname in sorted(MANIFEST_NAMES):
        path = repo_path / fname
        if not path.is_file():
            continue
        text = _read_capped(path, MAX_FILE_LINES)
        if not text.strip():
            continue
        events.append(RawEvent(
            source_type="code_scan",
            source_id=f"manifest:{fname}",
            timestamp=now,
            text=f"Manifest `{fname}`:\n\n{text}",
            metadata={"path": fname, "kind": "manifest"},
        ))

    # 2. Top-level .md docs — one event each.
    for fname in sorted(TOP_LEVEL_MD_NAMES):
        path = repo_path / fname
        if not path.is_file():
            continue
        text = _read_capped(path, MAX_FILE_LINES)
        if not text.strip():
            continue
        events.append(RawEvent(
            source_type="code_scan",
            source_id=f"file:{fname}",
            timestamp=now,
            text=f"Doc `{fname}`:\n\n{text}",
            metadata={"path": fname, "kind": "doc"},
        ))

    # 3. File-extension distribution — one summary event.
    all_files = _walk_source_files(repo_path)
    ext_counts: Counter[str] = Counter(path.suffix.lower() for path, _ in all_files)
    if ext_counts:
        lines = ["Source-file distribution:"]
        for ext, count in ext_counts.most_common(10):
            lines.append(f"  {ext}: {count} file(s)")
        events.append(RawEvent(
            source_type="code_scan",
            source_id="repo-summary",
            timestamp=now,
            text="\n".join(lines),
            metadata={"kind": "summary", "total_source_files": len(all_files)},
        ))

    # 4. Top-N largest source files (capped per-file).
    for rel_path, line_count in all_files[:TOP_N_FILES]:
        full = repo_path / rel_path
        text = _read_capped(full, MAX_FILE_LINES)
        if not text.strip():
            continue
        events.append(RawEvent(
            source_type="code_scan",
            source_id=f"file:{rel_path}",
            timestamp=now,
            text=f"Source file `{rel_path}` ({line_count} lines):\n\n```\n{text}\n```",
            metadata={"path": str(rel_path), "kind": "source", "line_count": line_count},
        ))

    return events

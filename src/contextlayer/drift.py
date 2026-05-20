"""Convention Drift Detection — check recent commits against indexed rules.

Per tasks/claude-code-prompt.md Feature 2. Heuristic, deterministic, no LLM
calls — designed to run in CI as a pre-merge gate.

Strategy:
  1. Pull all is_rule atoms from the SQLite store.
  2. For each rule that contains a negative obligation ("do not X", "never X",
     "avoid X", "deprecated"), extract the *forbidden subject tokens* — the
     identifier-like words that follow the prohibition.
  3. Walk the last N commits (or commits since a date) via `git log`. For each
     commit, collect its message, changed-file paths, and added-line diff text.
  4. For each rule, flag the commit when:
        - the forbidden tokens appear in the commit's text/diff, AND
        - the rule's scope (if any) matches at least one changed file (glob).
  5. Report violations with commit SHA, rule id, summary, and citation source.

We deliberately do not check positive obligations ("MUST use Result<T>")
because asserting "X was not used" from a diff requires understanding semantics
the heuristic can't reach. False positives are worse than missed violations
for a CI tool.
"""
from __future__ import annotations

import fnmatch
import json
import re
import sqlite3
import subprocess
from dataclasses import dataclass
from pathlib import Path

_NEGATIVE_PHRASES = re.compile(
    # Absorb common "do not <verb>" / "never <verb>" prefixes so the tail starts
    # directly on the forbidden subject. Without this, "Do not use X" would
    # leave 'use X' as the tail and the next contrastive regex would consume
    # 'use' as a boundary, eating the subject too.
    r"\b(do not (?:use|create|share|bypass|allow|pass|return|raise|import|call|run)|"
    r"don't (?:use|create|share|bypass|allow|pass|return|raise|import|call|run)|"
    r"never (?:use|create|share|bypass|allow|pass|return|raise|import|call|run)|"
    r"avoid (?:using|creating|sharing|bypassing|passing|returning|raising|importing|calling|running)|"
    r"stop using|do not|don't|never|avoid|deprecated|forbidden|disallow(?:ed)?)\b",
    re.IGNORECASE,
)
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_/.\-]*[A-Za-z0-9]")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "on",
    "for", "and", "or", "but", "not", "no", "do", "don", "use", "using",
    "with", "by", "from", "this", "that", "as", "at", "you", "we", "must",
    "should", "never", "always", "avoid", "deprecated", "rule", "scope", "all",
    "any", "ever", "have", "has", "had", "via", "per", "instead", "can",
    "module", "level",
}


@dataclass
class Violation:
    commit_sha: str
    short_sha: str
    commit_subject: str
    age_str: str
    rule_id: str
    rule_summary: str
    rule_scope: str | None
    rule_source: str | None
    matched_tokens: list[str]


# --------------------------------------------------------------------------
# Rule trigger extraction
# --------------------------------------------------------------------------

_CONTRASTIVE_RE = re.compile(
    r"[;.]|\b(use|instead|prefer|should use|must use|however|but|because|since)\b",
    re.IGNORECASE,
)


def _extract_triggers(summary: str) -> list[str]:
    """Pull forbidden-subject tokens out of a negative-obligation rule summary.

    Anatomy of a typical negative rule:

        "Do not use utils/db_helper; use Depends(get_session) instead."
         ^^^^^^^^^^^^^^^^^^^^^^^^^^   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
         forbidden subject            replacement (NOT a violation trigger)

    We slice the tail after the negative phrase up to the first contrastive
    boundary (`;`, `.`, or words like "instead", "use", "prefer", "because")
    so that we only capture the forbidden subject. Then we keep ONLY tokens
    that look like concrete code identifiers — snake_case, dotted, slashed,
    hyphenated, or camelCase. Bare English words (even long ones like
    "session", "requests", "sqlalchemy") are deliberately excluded because
    they trigger far too many false positives against unrelated commits.
    """
    if not summary:
        return []
    m = _NEGATIVE_PHRASES.search(summary)
    if not m:
        return []
    tail = summary[m.end():]
    boundary = _CONTRASTIVE_RE.search(tail)
    if boundary:
        tail = tail[:boundary.start()]

    out: list[str] = []
    seen: set[str] = set()
    for tok_m in _IDENT_RE.finditer(tail):
        tok = tok_m.group(0)
        low = tok.lower()
        if low in _STOPWORDS:
            continue
        is_compound = any(c in tok for c in "_/.-")
        is_camel = any(c.isupper() for c in tok[1:])
        if not (is_compound or is_camel):
            continue
        if low in seen:
            continue
        seen.add(low)
        out.append(low)
        if len(out) >= 3:
            break
    return out


def _format_source(refs: list[str]) -> str | None:
    """Render a source_refs list as a short citation, e.g. 'PR #8'."""
    if not refs:
        return None
    for ref in refs:
        if ref.startswith("pr:"):
            try:
                num = ref.split(":")[1]
                return f"PR #{num}"
            except IndexError:
                continue
    for ref in refs:
        if ref.startswith("commit:"):
            sha = ref.split(":", 1)[1][:7]
            return f"commit {sha}"
    return refs[0]


# --------------------------------------------------------------------------
# Git plumbing
# --------------------------------------------------------------------------

def _git_log(repo: Path, last: int | None, since: str | None) -> list[dict]:
    """Return a list of recent commits with their message + changed files + added-line diff."""
    sep = "<<<CL_END>>>"
    fsep = "<<<CL_FIELD>>>"
    fmt = f"%H{fsep}%h{fsep}%s{fsep}%cr{fsep}%b{sep}"
    args = ["git", "log", f"--pretty=format:{fmt}"]
    if since:
        args.append(f"--since={since}")
    if last:
        args.append(f"-n{last}")

    try:
        proc = subprocess.run(args, cwd=repo, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return []
    if proc.returncode != 0:
        return []

    commits: list[dict] = []
    for chunk in proc.stdout.split(sep):
        chunk = chunk.strip()
        if not chunk:
            continue
        parts = chunk.split(fsep)
        if len(parts) < 5:
            continue
        sha, short, subject, age, body = parts[0], parts[1], parts[2], parts[3], parts[4]

        # Pull changed files + a compact +line-only diff body.
        files_proc = subprocess.run(
            ["git", "show", "--name-only", "--pretty=format:", sha],
            cwd=repo, capture_output=True, text=True, check=False,
        )
        files = [ln.strip() for ln in files_proc.stdout.splitlines() if ln.strip()]

        diff_proc = subprocess.run(
            ["git", "show", "--pretty=format:", "--unified=0", sha],
            cwd=repo, capture_output=True, text=True, check=False,
        )
        added_lines = [
            ln[1:] for ln in diff_proc.stdout.splitlines()
            if ln.startswith("+") and not ln.startswith("+++")
        ]

        commits.append({
            "sha": sha,
            "short": short,
            "subject": subject,
            "age": age,
            "body": body,
            "files": files,
            "added": "\n".join(added_lines),
        })
    return commits


def _scope_matches(scope: str | None, files: list[str]) -> bool:
    """If the rule has a scope glob, at least one changed file must match it."""
    if not scope:
        return True
    pattern = scope.strip()
    # Translate `routes/**` style into something fnmatch understands.
    # fnmatch already handles `*` for path segments; we just normalize `**` → `*`.
    norm = pattern.replace("**", "*")
    for f in files:
        if fnmatch.fnmatch(f, norm):
            return True
        # Also match by leading-path containment (more forgiving).
        head = norm.split("*")[0].rstrip("/")
        if head and f.startswith(head + "/"):
            return True
        if head and f == head:
            return True
    return False


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

def check_drift(
    db_path: Path | str,
    repo_path: Path | str,
    *,
    last: int | None = 10,
    since: str | None = None,
) -> tuple[list[Violation], int]:
    """Return (violations, n_commits_checked)."""
    db_path = Path(db_path)
    repo_path = Path(repo_path)

    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT id, summary, scope, source_refs FROM atoms WHERE is_rule = 1"
        ).fetchall()
    finally:
        conn.close()

    rules: list[dict] = []
    for r in rows:
        try:
            refs = json.loads(r[3] or "[]")
        except (TypeError, ValueError):
            refs = []
        triggers = _extract_triggers(r[1] or "")
        if not triggers:
            continue
        # Commits that the rule was *extracted from* should never violate that
        # rule — they're the source of truth, not a regression. Collect their
        # full SHAs to suppress later.
        source_shas: set[str] = set()
        for ref in refs:
            if ref.startswith("commit:"):
                source_shas.add(ref.split(":", 1)[1])
        rules.append({
            "id": r[0],
            "summary": r[1],
            "scope": r[2],
            "source": _format_source(refs),
            "triggers": triggers,
            "source_shas": source_shas,
        })

    commits = _git_log(repo_path, last=last, since=since)
    violations: list[Violation] = []

    for commit in commits:
        haystack = "\n".join([
            commit["subject"], commit["body"], commit["added"], "\n".join(commit["files"]),
        ]).lower()

        for rule in rules:
            if commit["sha"] in rule["source_shas"]:
                # This commit is what the rule was extracted from. Skip.
                continue
            if not _scope_matches(rule["scope"], commit["files"]):
                continue
            matched = [t for t in rule["triggers"] if t in haystack]
            if not matched:
                continue
            violations.append(Violation(
                commit_sha=commit["sha"],
                short_sha=commit["short"],
                commit_subject=commit["subject"],
                age_str=commit["age"],
                rule_id=rule["id"],
                rule_summary=rule["summary"],
                rule_scope=rule["scope"],
                rule_source=rule["source"],
                matched_tokens=matched,
            ))

    return violations, len(commits)


def render_violations(violations: list[Violation], n_commits: int, n_rules: int) -> str:
    """Render a colored CLI-friendly report. Returns the rendered text."""
    from io import StringIO
    from rich.console import Console

    buf = StringIO()
    console = Console(file=buf, force_terminal=False, width=100)

    console.print(f"Checking last {n_commits} commits against {n_rules} rules...\n")

    if not violations:
        console.print(
            f"[green]✓ {n_commits} commits passed all convention checks.[/green]"
        )
        return buf.getvalue()

    # Each commit can be flagged by multiple rules — group for nicer output.
    by_commit: dict[str, list[Violation]] = {}
    for v in violations:
        by_commit.setdefault(v.short_sha, []).append(v)

    n = len(violations)
    word = "violation" if n == 1 else "violations"
    console.print(f"[yellow]⚠ {n} potential {word} found:[/yellow]\n")

    for short, vs in by_commit.items():
        first = vs[0]
        console.print(
            f"  [bold]commit {short}[/bold] ({first.age_str}) "
            f"\"{first.commit_subject}\""
        )
        for v in vs:
            console.print(f"  ┗━ Violates rule {v.rule_id}: \"{v.rule_summary}\"")
            if v.rule_scope:
                console.print(f"     Scope: {v.rule_scope}")
            if v.rule_source:
                console.print(f"     Source: {v.rule_source}")
            console.print(f"     Matched: {', '.join(v.matched_tokens)}")
        console.print("")

    passing = max(0, n_commits - len(by_commit))
    if passing:
        console.print(f"[green]✓ {passing} commits passed all convention checks.[/green]")
    return buf.getvalue()


def violations_to_json(
    violations: list[Violation], n_commits: int, n_rules: int
) -> dict:
    """Machine-readable form for --json / CI consumers."""
    return {
        "commits_checked": n_commits,
        "rules_checked": n_rules,
        "violations": [
            {
                "commit": v.short_sha,
                "commit_sha": v.commit_sha,
                "commit_subject": v.commit_subject,
                "age": v.age_str,
                "rule_id": v.rule_id,
                "rule_summary": v.rule_summary,
                "rule_scope": v.rule_scope,
                "source": v.rule_source,
                "matched_tokens": v.matched_tokens,
            }
            for v in violations
        ],
    }

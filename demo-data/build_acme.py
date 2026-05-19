#!/usr/bin/env python3
"""Deterministic generator for the acme-billing-api synthetic demo repo.

Creates demo-data/acme-billing-api/ as a fresh git repo with 15 commits, each
simulating a merged PR with embedded "review comments." The deliberate
conventions/decisions/deprecations/anti-patterns embedded are:

    PR #3   CONVENTION    Adopt Result<T> for domain errors
    PR #6   (reinforces #3)
    PR #8   DEPRECATION   Deprecate utils/db_helper; use SQLAlchemy session
    PR #11  DECISION      async-first for all I/O routes
    PR #14  ANTI-PATTERN  Never share SQLAlchemy session across requests

The remaining 10 PRs are ordinary work + 1-3 review comments each, providing
realistic background noise for the Haiku relevance filter (Stage 1 of the
extraction pipeline).

Output: demo-data/acme-billing-api/ — a nested git repo. Idempotent (re-running
deletes and re-creates). Pinned author + dates → reproducible commit SHAs across
runs.

Usage:
    uv run python demo-data/build_acme.py

See tasks/todo.md T+2-T+4 for the build slot this script belongs to,
and docs/specs/2026-05-18-contextlayer-design.md §8 + Appendix A #16 for
why this synthetic repo is the PRIMARY demo path.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

# ---------- configuration ---------------------------------------------------

REPO_PATH = Path(__file__).parent / "acme-billing-api"
AUTHOR_NAME = "Acme Engineering"
AUTHOR_EMAIL = "eng@acme.example"
START_DATE = datetime(2025, 9, 1, 10, 0, 0, tzinfo=timezone.utc)
DAYS_BETWEEN_PRS = 4

# Some review comments rotate authors; pinned to be deterministic.
REVIEWERS = ["alice", "bob", "carol", "dave", "eve"]


# ---------- data model ------------------------------------------------------

@dataclass
class FakePR:
    """One simulated merged PR — becomes one git commit in the output repo."""

    number: int
    subject: str
    body: str
    files: dict[str, str] = field(default_factory=dict)
    reviews: list[tuple[str, str]] = field(default_factory=list)

    def commit_message(self) -> str:
        """Format the commit message with the PR body and a delimited review block.

        Format (parsed by contextlayer.ingest.gh_prs for the synthetic shim):

            <subject>
            <blank>
            <body>
            <blank>
            ---REVIEW COMMENTS---
            @<reviewer>: <comment>
            @<reviewer>: <comment>
        """
        parts = [self.subject.rstrip(), "", self.body.rstrip()]
        if self.reviews:
            parts.extend(["", "---REVIEW COMMENTS---"])
            for who, what in self.reviews:
                parts.append(f"@{who}: {what.rstrip()}")
        return "\n".join(parts) + "\n"


# ---------- the 15 PRs (the actual leverage of the demo) --------------------

PRS: list[FakePR] = [
    # ----- PR #1: ordinary scaffold -----
    FakePR(
        number=1,
        subject="Initial scaffold for acme-billing-api",
        body=(
            "Set up FastAPI app structure, basic /healthz endpoint, "
            "requirements.txt. No business logic yet; this is just the skeleton "
            "to unblock parallel work on routes, models, and tests."
        ),
        files={
            "main.py": (
                "from fastapi import FastAPI\n\n"
                "app = FastAPI(title='acme-billing-api')\n\n"
                "@app.get('/healthz')\n"
                "async def healthz() -> dict[str, bool]:\n"
                "    return {'ok': True}\n"
            ),
            "requirements.txt": "fastapi\nuvicorn[standard]\nsqlalchemy\npydantic\n",
            "README.md": "# acme-billing-api\n\nBilling service for the Acme platform.\n",
        },
        reviews=[("alice", "lgtm — let's get this in to unblock parallel work.")],
    ),

    # ----- PR #2: sync-first cut, seeds the async debate that resolves in PR #11 -----
    FakePR(
        number=2,
        subject="Add /billing/customers and /billing/invoices endpoints",
        body=(
            "First cut at billing read endpoints. Sync handlers for this PR; "
            "most of these do DB I/O so we may want async, but landing sync now "
            "unblocks the frontend team. Worth a follow-up to set a project-wide "
            "policy on sync vs async."
        ),
        files={
            "routes/__init__.py": "",
            "routes/billing.py": (
                "from fastapi import APIRouter, Depends, HTTPException\n"
                "from sqlalchemy.orm import Session\n\n"
                "from models.customer import Customer\n"
                "from models.invoice import Invoice\n"
                "from utils.db import get_session\n\n"
                "router = APIRouter(prefix='/billing')\n\n\n"
                "@router.get('/customers/{customer_id}')\n"
                "def get_customer(customer_id: int, db: Session = Depends(get_session)):\n"
                "    customer = db.get(Customer, customer_id)\n"
                "    if customer is None:\n"
                "        raise HTTPException(404, 'customer not found')\n"
                "    return customer\n\n\n"
                "@router.get('/invoices/{invoice_id}')\n"
                "def get_invoice(invoice_id: int, db: Session = Depends(get_session)):\n"
                "    invoice = db.get(Invoice, invoice_id)\n"
                "    if invoice is None:\n"
                "        raise HTTPException(404, 'invoice not found')\n"
                "    return invoice\n"
            ),
            "models/__init__.py": "",
            "models/customer.py": "class Customer:\n    id: int\n    name: str\n",
            "models/invoice.py": "class Invoice:\n    id: int\n    customer_id: int\n    amount_cents: int\n",
            "utils/__init__.py": "",
            "utils/db.py": (
                "from sqlalchemy.orm import Session, sessionmaker\n\n"
                "SessionLocal = sessionmaker()\n\n"
                "def get_session() -> Session:\n"
                "    db = SessionLocal()\n"
                "    try:\n"
                "        yield db\n"
                "    finally:\n"
                "        db.close()\n"
            ),
        },
        reviews=[
            ("bob", "Should we be async-first here? Most of this is DB I/O."),
            ("alice", "Let's land sync to unblock the frontend team. We'll set the project-wide policy in a follow-up — see #11."),
            ("carol", "Use HTTPException for 404 in this PR but we should standardize errors across the codebase."),
        ],
    ),

    # ===== PR #3: CONVENTION — Result<T> =====
    FakePR(
        number=3,
        subject="Adopt Result<T> for domain errors (not exceptions)",
        body=(
            "After the Q3 incident where async exception propagation broke our distributed "
            "tracing (silently dropped spans whenever a route raised inside a gather), we're "
            "moving to a Result<T> pattern for ALL domain-level errors.\n\n"
            "Rule: any expected business-logic failure (validation, not-found, permission "
            "denied, conflict, payment-declined, etc.) MUST be returned as Result.err(reason); "
            "exceptions are reserved for truly exceptional conditions (DB unreachable, kernel "
            "panic, config error). Middleware can still raise — that boundary is well-defined.\n\n"
            "This PR adds types/result.py and migrates the customer-create endpoint as the "
            "first proof point. The rest of /billing gets migrated in #6."
        ),
        files={
            "types/__init__.py": "",
            "types/result.py": (
                "from __future__ import annotations\n"
                "from dataclasses import dataclass\n"
                "from typing import Generic, TypeVar\n\n"
                "T = TypeVar('T')\n\n"
                "@dataclass(frozen=True)\n"
                "class Ok(Generic[T]):\n"
                "    value: T\n"
                "    is_ok: bool = True\n\n"
                "@dataclass(frozen=True)\n"
                "class Err:\n"
                "    reason: str\n"
                "    is_ok: bool = False\n\n"
                "Result = Ok[T] | Err\n"
            ),
            "routes/customers.py": (
                "from fastapi import APIRouter\n"
                "from types.result import Ok, Err, Result\n\n"
                "router = APIRouter(prefix='/customers')\n\n"
                "@router.post('/')\n"
                "def create_customer(name: str) -> Result:\n"
                "    if not name.strip():\n"
                "        return Err('name must not be empty')\n"
                "    # ... insert ...\n"
                "    return Ok({'id': 1, 'name': name})\n"
            ),
        },
        reviews=[
            ("alice", "Strong +1. The async-tracing issue in Q3 was a nightmare and was 100% caused by the raise-everywhere pattern."),
            ("dave", "Result<T, E> with a typed E is more flexible long-term, but let's keep it simple with a single str reason for now — we can typed-error-up in v2 once we see real call sites."),
            ("bob", "Should we backport every existing endpoint? Yes but incrementally — #6 covers the /billing migration."),
            ("carol", "Document the middleware exception boundary explicitly — middleware CAN raise; domain handlers MUST Result."),
        ],
    ),

    # ----- PR #4: ordinary feature -----
    FakePR(
        number=4,
        subject="Add User model and JWT auth middleware skeleton",
        body=(
            "User model + JWT validation middleware. Validation is wired but no routes are "
            "auth-gated yet — that's a follow-up. /healthz stays explicitly public via an "
            "allowlist in the middleware."
        ),
        files={
            "models/user.py": "class User:\n    id: int\n    email: str\n",
            "middleware/__init__.py": "",
            "middleware/auth.py": (
                "PUBLIC_PATHS = {'/healthz', '/metrics'}\n\n"
                "async def jwt_middleware(request, call_next):\n"
                "    if request.url.path in PUBLIC_PATHS:\n"
                "        return await call_next(request)\n"
                "    # ... validate JWT ...\n"
                "    return await call_next(request)\n"
            ),
        },
        reviews=[
            ("eve", "Looks good. Scope the @requires_auth decorator to /billing/* in the follow-up so /healthz stays trivially open."),
        ],
    ),

    # ----- PR #5: ordinary tests -----
    FakePR(
        number=5,
        subject="Add pytest coverage for /billing routes",
        body=(
            "85% line coverage on routes/billing.py. Fixtures in conftest.py spin up an "
            "in-memory SQLite session, seed three customers + five invoices, tear down."
        ),
        files={
            "tests/__init__.py": "",
            "tests/conftest.py": (
                "import pytest\n"
                "from sqlalchemy import create_engine\n"
                "from sqlalchemy.orm import sessionmaker\n\n"
                "@pytest.fixture\n"
                "def db_session():\n"
                "    engine = create_engine('sqlite:///:memory:')\n"
                "    Session = sessionmaker(bind=engine)\n"
                "    session = Session()\n"
                "    yield session\n"
                "    session.close()\n"
            ),
            "tests/test_billing.py": (
                "def test_get_customer_404(db_session):\n"
                "    # placeholder — real assertions in the follow-up\n"
                "    assert True\n"
            ),
        },
        reviews=[
            ("alice", "Nice. Can we add a Result<T> assertion helper? `assert_ok(result, value=...)` would clean up tests once #6 lands."),
        ],
    ),

    # ===== PR #6: reinforces PR #3 =====
    FakePR(
        number=6,
        subject="Migrate /billing endpoints from raise-on-error to Result<T>",
        body=(
            "Per #3, refactor the existing /billing/customers and /billing/invoices endpoints "
            "from HTTPException-based error signaling to Result<T>. Tests updated. No behavior "
            "change at the HTTP layer — a small response_model_wrapper converts Result.err into "
            "the appropriate 4xx response.\n\n"
            "This locks in the pattern: domain handlers return Result<T>; HTTP shape is a "
            "concern of the response wrapper, not the business logic."
        ),
        files={
            "routes/billing.py": (
                "from fastapi import APIRouter, Depends\n"
                "from sqlalchemy.orm import Session\n\n"
                "from models.customer import Customer\n"
                "from types.result import Ok, Err, Result\n"
                "from utils.db import get_session\n\n"
                "router = APIRouter(prefix='/billing')\n\n\n"
                "@router.get('/customers/{customer_id}')\n"
                "def get_customer(customer_id: int, db: Session = Depends(get_session)) -> Result:\n"
                "    customer = db.get(Customer, customer_id)\n"
                "    if customer is None:\n"
                "        return Err('customer not found')\n"
                "    return Ok(customer)\n"
            ),
            "middleware/result_wrapper.py": (
                "# Converts a Result.err into the right HTTP status; Result.ok passes through.\n"
                "ERR_TO_STATUS = {'customer not found': 404, 'invoice not found': 404,\n"
                "                 'permission denied': 403, 'invalid input': 400}\n"
            ),
        },
        reviews=[
            ("bob", "Confirms the pattern works as designed. Let's keep going — user routes and invoice routes next sprint."),
            ("carol", "What about middleware errors that surface above the route? Those still raise — let's document that boundary explicitly in the README or a docs/ entry. (Per #3 reviewer thread.)"),
        ],
    ),

    # ----- PR #7: introduces db_helper that #8 deprecates -----
    FakePR(
        number=7,
        subject="Add utils/db_helper for one-off DB queries (legacy report)",
        body=(
            "Quick helper for the /billing/legacy-report endpoint, which doesn't fit the "
            "session-per-request pattern (it streams a multi-hour aggregation and we don't "
            "want to hold a request session open the whole time).\n\n"
            "Self-aware: this duplicates SQLAlchemy session handling. Flagging as a likely "
            "follow-up to consolidate."
        ),
        files={
            "utils/db_helper.py": (
                "import sqlalchemy\n\n"
                "def fetch_one(query: str) -> dict | None:\n"
                "    # opens its own connection, runs query, closes — bypasses request session\n"
                "    engine = sqlalchemy.create_engine('postgresql://...')\n"
                "    with engine.connect() as conn:\n"
                "        row = conn.execute(query).fetchone()\n"
                "        return dict(row) if row else None\n"
            ),
            "routes/legacy.py": (
                "from fastapi import APIRouter\n"
                "from utils.db_helper import fetch_one\n\n"
                "router = APIRouter()\n\n"
                "@router.get('/billing/legacy-report')\n"
                "def legacy_report():\n"
                "    return fetch_one('SELECT * FROM legacy_reports LIMIT 1')\n"
            ),
        },
        reviews=[
            ("alice", "+1 to unblock, but this is going to bite us — let's revisit. Duplicate session handling means we can't enforce the connection pool limit."),
        ],
    ),

    # ===== PR #8: DEPRECATION =====
    FakePR(
        number=8,
        subject="Deprecate utils/db_helper; standardize on injected SQLAlchemy session",
        body=(
            "#7 introduced db_helper as a stopgap and it's already biting us. Last week's "
            "staging incident: four routes called db_helper concurrently during a load test, "
            "each opened its own connection, blew through the pool ceiling (20), and the rest "
            "of the app stalled on connection acquisition for 90 seconds.\n\n"
            "Marking db_helper deprecated. NEW CODE MUST use the SQLAlchemy session injected "
            "via Depends(get_session) — that path goes through our pool, gets per-request "
            "lifecycle, and plays nicely with our async-first direction (#11).\n\n"
            "Migration: db_helper currently has exactly one caller (legacy.py). Rewriting it "
            "this PR. Adding a DeprecationWarning on import; will hard-fail (RuntimeError) "
            "after Sprint 2027-Q1 once we're sure nobody else has pulled it in.\n\n"
            "Anti-pattern: if you find yourself reaching for db_helper because 'the session "
            "is too short-lived,' you probably want to fix the route lifecycle, not bypass "
            "the pool."
        ),
        files={
            "utils/db_helper.py": (
                "import warnings\n\n"
                "warnings.warn(\n"
                "    'utils.db_helper is DEPRECATED. Use Depends(get_session) from utils.db. '\n"
                "    'See PR #8 in the changelog. Hard-fails after 2027-Q1.',\n"
                "    DeprecationWarning, stacklevel=2,\n"
                ")\n\n"
                "def fetch_one(query: str):\n"
                "    raise RuntimeError('db_helper.fetch_one removed — use Depends(get_session)')\n"
            ),
            "routes/legacy.py": (
                "from fastapi import APIRouter, Depends\n"
                "from sqlalchemy.orm import Session\n"
                "from utils.db import get_session\n\n"
                "router = APIRouter()\n\n"
                "@router.get('/billing/legacy-report')\n"
                "def legacy_report(db: Session = Depends(get_session)):\n"
                "    row = db.execute('SELECT * FROM legacy_reports LIMIT 1').fetchone()\n"
                "    return dict(row) if row else None\n"
            ),
            "docs/db-helper-deprecation.md": (
                "# utils/db_helper is deprecated\n\n"
                "Use `Depends(get_session)` from `utils/db.py`. Hard-fails after 2027-Q1.\n"
            ),
        },
        reviews=[
            ("alice", "Reason for deprecate vs immediate-remove: we want a grace window in case any external/private fork pulled this in. After 2027-Q1, RuntimeError."),
            ("bob", "Connection pool exhaustion under concurrent calls was the proximate cause — but the deeper issue is that bypassing get_session means we can't ever enforce per-request lifecycle."),
            ("dave", "Should we add a custom linter rule? Yes, see #14's pre-commit hook setup."),
        ],
    ),

    # ----- PR #9: introduces async, seeds policy debate that resolves in PR #11 -----
    FakePR(
        number=9,
        subject="Add async /billing/customers/{id}/usage (fan-out fetch)",
        body=(
            "First async endpoint in the codebase. Fetches a customer's usage data across "
            "three downstream services (metering, payments, support) in parallel via "
            "asyncio.gather. Sequentially this would be ~600ms; in parallel it's ~200ms.\n\n"
            "Note: this is now a sync/async mix in routes/billing.py. We need to set a "
            "project policy — see #11."
        ),
        files={
            "routes/billing.py": (
                "from fastapi import APIRouter, Depends\n"
                "import asyncio, httpx\n\n"
                "router = APIRouter(prefix='/billing')\n\n"
                "@router.get('/customers/{customer_id}/usage')\n"
                "async def get_usage(customer_id: int):\n"
                "    async with httpx.AsyncClient() as client:\n"
                "        metering, payments, support = await asyncio.gather(\n"
                "            client.get(f'http://metering/customers/{customer_id}'),\n"
                "            client.get(f'http://payments/customers/{customer_id}'),\n"
                "            client.get(f'http://support/customers/{customer_id}'),\n"
                "        )\n"
                "    return {\n"
                "        'metering': metering.json(), 'payments': payments.json(),\n"
                "        'support': support.json(),\n"
                "    }\n"
            ),
        },
        reviews=[
            ("carol", "Faster, but the rest of /billing is sync — bikeshedding will follow if we don't pick a policy. See #11."),
            ("alice", "+1 to set the policy soon. Async-for-I/O makes sense as the default."),
        ],
    ),

    # ----- PR #10: introduces cache that PR #12 fixes -----
    FakePR(
        number=10,
        subject="Add in-process LRU cache for customer-by-id lookups",
        body=(
            "Cache hits on /billing/customers/{id} reduce DB pressure noticeably (we see "
            "~30% repeat reads in the 5-minute window of the homepage SSR). functools.lru_cache "
            "doesn't fit because we need TTL; using cachetools.TTLCache, 1024 entries, 300s TTL.\n\n"
            "Cache key is just customer_id — the response doesn't depend on the requesting user."
        ),
        files={
            "utils/cache.py": (
                "from cachetools import TTLCache\n\n"
                "customer_cache = TTLCache(maxsize=1024, ttl=300)\n\n"
                "def get_customer_cached(customer_id: int, fetch_fn):\n"
                "    if customer_id not in customer_cache:\n"
                "        customer_cache[customer_id] = fetch_fn(customer_id)\n"
                "    return customer_cache[customer_id]\n"
            ),
        },
        reviews=[
            ("dave", "Be careful with cached objects + auth — if the response ever depends on the requesting user's permissions, you need the user in the cache key. Confirm 'doesn't depend on user' stays true."),
            ("bob", "What happens under concurrent requests for an uncached id? We'll have a thundering-herd. Adding to my followups."),
        ],
    ),

    # ===== PR #11: DECISION =====
    FakePR(
        number=11,
        subject="Decision: async-first for all I/O routes (DB, HTTP, queue)",
        body=(
            "#2 had the sync-vs-async debate. #9 introduced an async route. We've been "
            "bikeshedding case-by-case in every PR review since. Locking the policy:\n\n"
            "    Any route handler that does I/O (DB query, external HTTP, queue write, "
            "    file read) MUST be `async def`. Pure-compute routes can stay `def`.\n\n"
            "Rationale:\n"
            "  1. Connection-pool throughput. Sync handlers block worker threads on DB I/O. "
            "     With 8 uvicorn workers and 30ms average DB latency, we cap at ~270 req/s; "
            "     async lifts that ~3x in load testing.\n"
            "  2. asyncio.gather fan-out (see #9) is impossible without async.\n"
            "  3. Avoids the mix-and-match async-sync subprocess footguns (run_in_executor "
            "     dance, deadlocks when async handler calls sync DB).\n\n"
            "Migration:\n"
            "  - All existing /billing sync handlers rewritten async this PR.\n"
            "  - /billing/legacy-report (uses #8's session pattern) converted async.\n"
            "  - CI check: a pytest-collect hook fails the build if any FastAPI route handler "
            "    awaits a known-async fn (e.g., session.execute) without being async-def."
        ),
        files={
            "docs/async-first.md": (
                "# Async-first policy (PR #11)\n\n"
                "All route handlers that do I/O MUST be `async def`.\n\n"
                "Exceptions: pure-compute routes (rare).\n\n"
                "Enforcement: CI check via tools/check_async_routes.py.\n"
            ),
            "routes/billing.py": (
                "from fastapi import APIRouter, Depends\n"
                "from sqlalchemy.ext.asyncio import AsyncSession\n"
                "from utils.db import get_async_session\n"
                "from types.result import Ok, Err, Result\n\n"
                "router = APIRouter(prefix='/billing')\n\n"
                "@router.get('/customers/{customer_id}')\n"
                "async def get_customer(customer_id: int, db: AsyncSession = Depends(get_async_session)) -> Result:\n"
                "    customer = await db.get(Customer, customer_id)\n"
                "    if customer is None:\n"
                "        return Err('customer not found')\n"
                "    return Ok(customer)\n"
            ),
            "tools/check_async_routes.py": (
                "# AST-walks routes/ and fails if a route handler awaits an async call without being async-def.\n"
                "pass\n"
            ),
        },
        reviews=[
            ("eve", "Strong +1. Eliminates the case-by-case bikeshedding."),
            ("alice", "What about /billing/legacy-report (uses db_helper, deprecated in #8)? Convert as part of this PR — done."),
            ("bob", "CI enforcement is what makes this stick. Without it, drift in 6 months. The check_async_routes.py hook is worth a code-review on its own."),
            ("dave", "Pure-compute exception is right — we have one of those (/billing/calc-tax) that shouldn't get the async treatment."),
        ],
    ),

    # ----- PR #12: ordinary bug fix; references PR #10 -----
    FakePR(
        number=12,
        subject="Fix race in customer cache under concurrent uncached reads",
        body=(
            "#10's TTLCache wasn't safe under concurrent requests for the same uncached id: "
            "two requests arriving simultaneously both saw the miss, both ran the DB fetch, "
            "both wrote to the cache. Not corrupting state but wasting DB roundtrips and "
            "causing the very pool pressure the cache was supposed to reduce.\n\n"
            "Fix: asyncio.Lock per cache key. First request fetches and populates; subsequent "
            "concurrent requests for the same id wait on the lock and then read from cache."
        ),
        files={
            "utils/cache.py": (
                "import asyncio\n"
                "from cachetools import TTLCache\n\n"
                "customer_cache = TTLCache(maxsize=1024, ttl=300)\n"
                "_locks: dict[int, asyncio.Lock] = {}\n\n"
                "async def get_customer_cached(customer_id: int, fetch_fn):\n"
                "    if customer_id in customer_cache:\n"
                "        return customer_cache[customer_id]\n"
                "    lock = _locks.setdefault(customer_id, asyncio.Lock())\n"
                "    async with lock:\n"
                "        if customer_id not in customer_cache:\n"
                "            customer_cache[customer_id] = await fetch_fn(customer_id)\n"
                "    return customer_cache[customer_id]\n"
            ),
        },
        reviews=[
            ("carol", "Good catch. Worth adding a Prometheus metric for cache-stampede events — count of waits on the lock — so we can tell if our TTL is wrong."),
        ],
    ),

    # ----- PR #13: ordinary infra -----
    FakePR(
        number=13,
        subject="Add /metrics endpoint and route timing instrumentation",
        body=(
            "Prometheus instrumentation: request count, request duration histogram, error "
            "rate, per-route labels. Scrape endpoint is /metrics — added to PUBLIC_PATHS in "
            "the auth middleware (per #4) since scrapers don't authenticate."
        ),
        files={
            "middleware/metrics.py": (
                "from prometheus_client import Counter, Histogram\n\n"
                "REQUEST_COUNT = Counter('http_requests_total', '...', ['route', 'status'])\n"
                "REQUEST_DURATION = Histogram('http_request_duration_seconds', '...', ['route'])\n"
            ),
        },
        reviews=[
            ("eve", "lgtm — make sure /metrics is in the public allowlist in middleware/auth.py (PUBLIC_PATHS). Confirmed it is."),
        ],
    ),

    # ===== PR #14: ANTI-PATTERN =====
    FakePR(
        number=14,
        subject="Fix anti-pattern: shared SQLAlchemy session across requests (routes/legacy.py)",
        body=(
            "Hot one. Found this during a code-archaeology pass following the #8 migration: "
            "routes/legacy.py at one point had:\n\n"
            "    from utils.db import SessionLocal\n"
            "    _shared = SessionLocal()  # MODULE-LEVEL — created once per worker\n\n"
            "    @router.get('/billing/legacy-export')\n"
            "    async def legacy_export():\n"
            "        return _shared.query(...).all()\n\n"
            "Why this is an anti-pattern:\n"
            "  1. Sessions are NOT thread-safe and NOT async-task-safe. Two concurrent "
            "     requests on the same worker share the same Session, the same transaction, "
            "     and the same connection. One request's rollback affects another's writes.\n"
            "  2. Connection leaks. The session is never close()d (process lifetime); the "
            "     connection sits in 'idle in transaction' forever. We saw this manifest as "
            "     'too many connections' alerts in staging.\n"
            "  3. SQLAlchemy's identity map grows unboundedly, slowly OOMing the worker.\n\n"
            "Rule, codified now: a SQLAlchemy session MUST have request-scoped lifecycle. "
            "Use `Depends(get_session)` (sync) or `Depends(get_async_session)` (async per "
            "#11). NEVER create a module-level session. NEVER pass a session between "
            "background tasks.\n\n"
            "This PR:\n"
            "  - Fixes routes/legacy.py to use Depends(get_async_session).\n"
            "  - Adds tools/lint_session_check.py — a pre-commit hook + CI check that AST-"
            "    walks the codebase looking for `SessionLocal()` outside of a function body "
            "    and fails the build.\n"
            "  - Adds a 'Anti-patterns we've burned ourselves on' section to README."
        ),
        files={
            "routes/legacy.py": (
                "from fastapi import APIRouter, Depends\n"
                "from sqlalchemy.ext.asyncio import AsyncSession\n"
                "from utils.db import get_async_session\n\n"
                "router = APIRouter()\n\n"
                "@router.get('/billing/legacy-export')\n"
                "async def legacy_export(db: AsyncSession = Depends(get_async_session)):\n"
                "    rows = await db.execute('SELECT ...')\n"
                "    return [dict(r) for r in rows]\n"
            ),
            "tools/lint_session_check.py": (
                "# AST-walks for module-level `SessionLocal()` and fails. Wired into pre-commit + CI.\n"
                "pass\n"
            ),
            "docs/anti-patterns.md": (
                "# Anti-patterns we've burned ourselves on\n\n"
                "## 1. Sharing a SQLAlchemy session across requests (PR #14)\n\n"
                "Sessions are request-scoped. Always use Depends(get_session). "
                "Never module-level. Lint check enforces.\n"
            ),
        },
        reviews=[
            ("alice", "How did this slip past code review? The #8 db_helper deprecation migrated routes/legacy.py to a get_session pattern but the legacy_export handler was added in a separate later PR and reused the old pattern by reflex."),
            ("bob", "+1 to the lint rule. Catches this at PR time before it ever runs. Make sure the rule also flags `async_sessionmaker()()` calls outside function scope — same anti-pattern, different surface."),
            ("dave", "Add a one-liner under README → 'Anti-patterns' so new hires hit it on day one. Done in the docs/anti-patterns.md."),
            ("carol", "Worth a postmortem mention? The 'too many connections' alert from two weeks ago is now explained."),
        ],
    ),

    # ----- PR #15: ordinary docs -----
    FakePR(
        number=15,
        subject="Onboarding doc + README pass for new hires",
        body=(
            "Documentation pass for engineers joining the billing team. Covers:\n"
            "  - Result<T> pattern (#3, reinforced #6)\n"
            "  - Async-first policy for I/O routes (#11)\n"
            "  - SQLAlchemy session injection via Depends (#8)\n"
            "  - Anti-pattern: don't share sessions across requests (#14)\n"
            "  - Deprecated: utils/db_helper (#8)\n\n"
            "These are the things we keep telling new hires verbally — capturing in writing."
        ),
        files={
            "docs/onboarding.md": (
                "# Onboarding\n\n"
                "Read before writing code in this service:\n\n"
                "1. `Result<T>` for domain errors, not exceptions (PR #3, #6)\n"
                "2. Async-first for I/O routes (PR #11)\n"
                "3. SQLAlchemy session: always Depends(get_session) (PR #8)\n"
                "4. Anti-pattern: never share a session across requests (PR #14)\n"
                "5. utils/db_helper is deprecated — don't use it (PR #8)\n"
            ),
            "README.md": (
                "# acme-billing-api\n\n"
                "Billing service.\n\n"
                "## Conventions\n\n"
                "See [docs/onboarding.md](docs/onboarding.md) for the team conventions. TL;DR:\n\n"
                "- Domain errors → `Result<T>` (not exceptions)\n"
                "- I/O routes → `async def`\n"
                "- DB session → `Depends(get_session)`, request-scoped\n"
                "- Don't share sessions across requests (lint enforced)\n"
            ),
        },
        reviews=[
            ("eve", "+1, this is literally what we say to every new hire. Cross-reference in the README so they hit it from the entry point."),
        ],
    ),
]


# ---------- driver ----------------------------------------------------------

def run_git(args: list[str], cwd: Path, env_extra: dict | None = None) -> None:
    """Run a git subcommand with author identity pinned for reproducibility."""
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": AUTHOR_EMAIL,
    })
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.stderr.write(f"git {' '.join(args)} failed:\n{result.stderr}")
        sys.exit(result.returncode)


def write_files(files: dict[str, str]) -> None:
    for relpath, content in files.items():
        full = REPO_PATH / relpath
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)


def main() -> int:
    # Idempotency
    if REPO_PATH.exists():
        shutil.rmtree(REPO_PATH)
    REPO_PATH.mkdir(parents=True)

    run_git(["init", "-q", "--initial-branch=main"], cwd=REPO_PATH)
    run_git(["config", "user.name", AUTHOR_NAME], cwd=REPO_PATH)
    run_git(["config", "user.email", AUTHOR_EMAIL], cwd=REPO_PATH)
    # Pin commit signing off — never sign in a synthetic repo
    run_git(["config", "commit.gpgsign", "false"], cwd=REPO_PATH)

    print(f"Generating {len(PRS)} PRs in {REPO_PATH} ...")

    for i, pr in enumerate(PRS):
        write_files(pr.files)
        commit_date = (START_DATE + timedelta(days=i * DAYS_BETWEEN_PRS)).isoformat()
        run_git(["add", "-A"], cwd=REPO_PATH)
        run_git(
            ["commit", "-q", "-m", pr.commit_message()],
            cwd=REPO_PATH,
            env_extra={
                "GIT_AUTHOR_DATE": commit_date,
                "GIT_COMMITTER_DATE": commit_date,
            },
        )

    # Verify
    log = subprocess.run(
        ["git", "log", "--oneline"], cwd=REPO_PATH, capture_output=True, text=True,
    )
    print()
    print(f"✓ {len(PRS)} commits written:")
    for line in log.stdout.strip().split("\n"):
        print(f"  {line}")

    # Counts
    counts = subprocess.run(
        ["git", "rev-list", "--count", "HEAD"], cwd=REPO_PATH, capture_output=True, text=True,
    )
    assert int(counts.stdout.strip()) == len(PRS), "commit count mismatch"
    print(f"\n✓ {counts.stdout.strip()} commits confirmed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

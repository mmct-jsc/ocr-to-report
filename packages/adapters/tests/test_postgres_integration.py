"""Integration tests against a real PostgreSQL service container.

Gated on BOTH the ``integration`` pytest marker AND the ``OCR2R_TEST_DB_URL``
environment variable. The marker keeps these out of the default
``pytest`` invocation (CI's main ``ci.yml`` excludes ``-m integration``);
the env-var gate makes the module a hard skip — not a failure — when
the URL is missing, so a dev running ``uv run pytest`` locally without
a postgres container doesn't get red.

CI runs this via ``.github/workflows/integration.yml`` which provides
both the service container and the URL.

Local run::

    docker run --rm -d -p 5432:5432 --name ocr2r-pg \\
        -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=ocr2r_test \\
        postgres:16-alpine
    OCR2R_TEST_DB_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/ocr2r_test \\
        uv run pytest -m integration packages/adapters/tests/ -v

What this validates that the unit suite cannot:
    1. ``Base.metadata.create_all`` succeeds against postgres — proves
       every column type / constraint maps cleanly across dialects.
    2. The full repository round-trip (TenantRepo) works on postgres,
       not just sqlite — catches SQL that's permissive on sqlite but
       strict on postgres (NULL handling, type coercion).
    3. ``tenant_scoped_session`` correctly SETs the ``app.tenant_id``
       GUC. This is the pillar of postgres RLS isolation; if it
       silently no-ops in production, every tenant sees every row.
"""

from __future__ import annotations

import base64
import os
import secrets
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base
from ocr_to_report.adapters.db.repositories import TenantRepo
from ocr_to_report.adapters.db.session import tenant_scoped_session

pytestmark = pytest.mark.integration

DB_URL = os.getenv("OCR2R_TEST_DB_URL")

if not DB_URL or not DB_URL.startswith("postgresql"):
    pytest.skip(
        "OCR2R_TEST_DB_URL not set (or not a postgresql:// URL); "
        "skipping postgres integration tests. See module docstring for setup.",
        allow_module_level=True,
    )


# ─── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def kek_env(monkeypatch: pytest.MonkeyPatch) -> str:
    """Stable KEK for the duration of one test."""
    kek = base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode()
    monkeypatch.setenv("OCR2R_KEK_B64", kek)
    return kek


@pytest.fixture
def encryptor(kek_env: str) -> EnvelopeEncryptor:
    return EnvelopeEncryptor(EnvKEKProvider())


@pytest.fixture
async def pg_engine() -> AsyncIterator[AsyncEngine]:
    """One engine per test — small suite, simple lifecycle."""
    assert DB_URL is not None  # guarded by module-level skip above
    engine = create_async_engine(DB_URL, future=True, echo=False)
    yield engine
    await engine.dispose()


@pytest.fixture
async def pg_session(pg_engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Fresh schema per test against the postgres service container.

    Drop-all then create-all per test is wasteful at scale but rock-solid
    for isolation while the integration suite is small. If/when this grows
    past ~20 tests, swap to a single create_all + per-test transaction
    rollback driven by a session-scoped engine fixture.
    """
    async with pg_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(pg_engine, expire_on_commit=False)
    async with sm() as s:
        yield s
        await s.rollback()


# ─── tests ────────────────────────────────────────────────────────────


# Every shipped table from `models.py`. If a future migration adds a
# table, the unit tests still pass (sqlite is lenient) but this set lags
# until the dev updates it — that's the loud reminder we want.
EXPECTED_TABLES = frozenset(
    {
        "tenants",
        "api_keys",
        "webhooks",
        "jobs",
        "transcripts",
        "audit_log",
        "usage_records",
        "idempotency_keys",
        "result_cache",
        "batch_submissions",
        "tenant_overrides",
        "tenant_provider_credentials",  # v0.3.0
    }
)


async def test_schema_creates_on_postgres(pg_session: AsyncSession) -> None:
    """``Base.metadata.create_all`` runs cleanly against real postgres.

    Catches any column type or constraint that's sqlite-only — the unit
    suite uses sqlite and would not surface dialect drift. The pg_session
    fixture already ran create_all; this just verifies the tables landed.
    """
    result = await pg_session.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' ORDER BY table_name"
        )
    )
    tables = {row[0] for row in result.all()}
    missing = EXPECTED_TABLES - tables
    assert not missing, f"Expected tables missing on postgres: {sorted(missing)}"


async def test_tenant_repo_round_trip_postgres(
    pg_session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    """Full TenantRepo create/get round-trip against postgres.

    The repo writes LargeBinary (the wrapped DEK) and a dict column
    (profiles_enabled); both are dialect-sensitive in subtle ways. This
    is the canary for postgres-specific repo regressions.
    """
    repo = TenantRepo(pg_session, encryptor)
    tenant, dek_plain = await repo.create(name="Acme PG", slug="acme-pg")
    assert tenant.id is not None
    # Wrapped DEK persisted and unwraps back to the original plaintext.
    fetched = await repo.get(tenant.id)
    assert fetched is not None
    assert fetched.name == "Acme PG"
    assert await repo.unwrap_dek(fetched) == dek_plain


async def test_tenant_scoped_session_sets_app_tenant_id(pg_engine: AsyncEngine) -> None:
    """``tenant_scoped_session`` SETs the ``app.tenant_id`` GUC on postgres.

    Production RLS policies key off ``current_setting('app.tenant_id', true)``.
    If the helper silently no-ops on postgres (e.g. a future refactor broke
    the dialect check), every tenant would see every row and unit tests
    wouldn't notice — they run on sqlite, where the helper IS a no-op.
    """
    sm = async_sessionmaker(pg_engine, expire_on_commit=False)
    tid = uuid.uuid4()
    async with tenant_scoped_session(sm, tid) as s:
        result = await s.execute(text("SELECT current_setting('app.tenant_id', true)"))
        assert result.scalar() == str(tid)

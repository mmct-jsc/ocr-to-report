"""v0.3.0 migration contract tests against a real PostgreSQL service.

Gated on the ``integration`` pytest marker AND ``OCR2R_TEST_DB_URL`` —
same pattern as ``test_postgres_integration.py``. The local
``test_migrations.py`` covers the SQLite-portable shape of these
migrations (table + column landing); this module pins the
postgres-only details that SQLite can't validate:

1. The ``tenant_provider_credentials`` table has the partial unique
   index ``ix_tenant_provider_credentials_active`` keyed on
   ``(tenant_id, provider) WHERE active = TRUE``. Two inactive rows
   for the same ``(tenant, provider)`` are allowed; two active rows
   are NOT.
2. ``usage_records.billing_path`` carries the CHECK constraint
   ``billing_path IN ('platform', 'byok')``.
3. Existing ``usage_records`` rows default to ``billing_path =
   'platform'`` (the migration must backfill any pre-existing rows).
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]
DB_URL = os.getenv("OCR2R_TEST_DB_URL")

if not DB_URL or not DB_URL.startswith("postgresql"):
    pytest.skip(
        "OCR2R_TEST_DB_URL not set (or not postgresql://); skipping v0.3.0 "
        "migration contract tests. See test_postgres_integration.py for setup.",
        allow_module_level=True,
    )


# asyncpg is the default driver in our normal sessions, but alembic uses
# a sync engine internally — strip the +asyncpg suffix so the same env
# var works for both contexts.
def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg://", "postgresql://")


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    """One sync engine per test against a clean schema.

    Drop-all via downgrade-to-base keeps each test isolated. The
    integration-pg workflow's service container gets reset between job
    runs, but in-job tests share the DB."""
    assert DB_URL is not None  # guarded by module-level skip
    sync_url = _sync_url(DB_URL)
    cfg = _make_alembic_config(sync_url)
    # Reset to a clean state before each test.
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    engine = create_engine(sync_url, future=True)
    yield engine
    engine.dispose()


def test_tenant_provider_credentials_table_lands(pg_engine: Engine) -> None:
    """The new table exists after ``alembic upgrade head``."""
    inspector = inspect(pg_engine)
    assert "tenant_provider_credentials" in inspector.get_table_names()
    cols = {c["name"] for c in inspector.get_columns("tenant_provider_credentials")}
    assert {
        "id",
        "tenant_id",
        "provider",
        "encrypted_api_key",
        "model_overrides",
        "region",
        "active",
        "created_at",
        "updated_at",
        "rotated_at",
    } <= cols, f"missing columns: {cols}"


def test_partial_unique_active_credential_per_provider(pg_engine: Engine) -> None:
    """Two active rows for the same (tenant, provider) is rejected; two
    inactive rows (or one active + one inactive) is allowed.

    This is the postgres-only invariant — SQLite's partial-index support
    is dialect-different; the repo also enforces it transactionally for
    defense in depth (Task 2)."""
    with pg_engine.begin() as conn:
        tid = str(uuid.uuid4())
        # Seed a tenant (FK target).
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, sla_tier, dek_wrapped, "
                "profiles_enabled, pipeline_id, created_at, updated_at) "
                "VALUES (:id, 'T1', 't1', 'standard', :dek, '{}', "
                "'default_v1', now(), now())"
            ),
            {"id": tid, "dek": b"\x00" * 60},
        )

        def _insert(provider: str, active: bool, rid: str | None = None) -> None:
            conn.execute(
                text(
                    "INSERT INTO tenant_provider_credentials "
                    "(id, tenant_id, provider, encrypted_api_key, "
                    "model_overrides, active, created_at, updated_at) "
                    "VALUES (:id, :tid, :p, :k, '{}', :a, now(), now())"
                ),
                {
                    "id": rid or str(uuid.uuid4()),
                    "tid": tid,
                    "p": provider,
                    "k": b"\x01" * 32,
                    "a": active,
                },
            )

        # One active row OK.
        _insert("anthropic", active=True)
        # Second active row for the same (tenant, provider) MUST violate.
        with pytest.raises(IntegrityError):
            _insert("anthropic", active=True)


def test_two_inactive_rows_for_same_provider_allowed(pg_engine: Engine) -> None:
    """Inactive rows accumulate (rotation history) — the partial index
    only constrains active=TRUE."""
    with pg_engine.begin() as conn:
        tid = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, sla_tier, dek_wrapped, "
                "profiles_enabled, pipeline_id, created_at, updated_at) "
                "VALUES (:id, 'T2', 't2', 'standard', :dek, '{}', "
                "'default_v1', now(), now())"
            ),
            {"id": tid, "dek": b"\x00" * 60},
        )

        def _insert(active: bool) -> None:
            conn.execute(
                text(
                    "INSERT INTO tenant_provider_credentials "
                    "(id, tenant_id, provider, encrypted_api_key, "
                    "model_overrides, active, created_at, updated_at) "
                    "VALUES (:id, :tid, 'anthropic', :k, '{}', :a, now(), now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "tid": tid,
                    "k": b"\x02" * 32,
                    "a": active,
                },
            )

        _insert(active=False)
        _insert(active=False)
        _insert(active=False)
        # No assertion — the inserts simply must not raise.


def test_usage_records_billing_path_check_constraint(pg_engine: Engine) -> None:
    """``billing_path`` only accepts the two named values."""
    with pg_engine.begin() as conn:
        tid = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, sla_tier, dek_wrapped, "
                "profiles_enabled, pipeline_id, created_at, updated_at) "
                "VALUES (:id, 'T3', 't3', 'standard', :dek, '{}', "
                "'default_v1', now(), now())"
            ),
            {"id": tid, "dek": b"\x00" * 60},
        )

        def _insert_usage(billing_path: str) -> None:
            conn.execute(
                text(
                    "INSERT INTO usage_records "
                    "(id, tenant_id, period_start, period_end, "
                    "transcripts_processed, tokens_input, tokens_output, "
                    "cache_read_tokens, cache_creation_tokens, usd_cost, "
                    "billing_path, created_at, updated_at) "
                    "VALUES (:id, :tid, now(), now(), 0, 0, 0, 0, 0, 0, "
                    ":bp, now(), now())"
                ),
                {"id": str(uuid.uuid4()), "tid": tid, "bp": billing_path},
            )

        _insert_usage("platform")
        _insert_usage("byok")
        with pytest.raises(IntegrityError):
            _insert_usage("not-a-billing-path")


def test_usage_records_billing_path_default_is_platform(pg_engine: Engine) -> None:
    """An INSERT that omits ``billing_path`` defaults to ``'platform'``.

    This protects existing call sites (and any backfilled rows from the
    0004 migration) — they all bill against the platform."""
    with pg_engine.begin() as conn:
        tid = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, slug, sla_tier, dek_wrapped, "
                "profiles_enabled, pipeline_id, created_at, updated_at) "
                "VALUES (:id, 'T4', 't4', 'standard', :dek, '{}', "
                "'default_v1', now(), now())"
            ),
            {"id": tid, "dek": b"\x00" * 60},
        )
        rid = str(uuid.uuid4())
        conn.execute(
            text(
                "INSERT INTO usage_records "
                "(id, tenant_id, period_start, period_end, "
                "transcripts_processed, tokens_input, tokens_output, "
                "cache_read_tokens, cache_creation_tokens, usd_cost, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, now(), now(), 0, 0, 0, 0, 0, 0, now(), now())"
            ),
            {"id": rid, "tid": tid},
        )
        result = conn.execute(
            text("SELECT billing_path FROM usage_records WHERE id = :id"),
            {"id": rid},
        )
        assert result.scalar() == "platform"

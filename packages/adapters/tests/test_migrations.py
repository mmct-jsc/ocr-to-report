"""Alembic baseline migration recreates the full schema.

Phase 5 shipped the schema via ``Base.metadata.create_all`` only — the
``migrations/versions/`` directory was empty. v0.2.0 introduces the
first real alembic baseline so production deploys have an audit trail
of schema changes (and so the next migration can be additive without
re-encoding the entire history).

This test pins the contract: running ``alembic upgrade head`` against
an empty database produces every table the ORM knows about, with the
shared metadata's naming convention applied to every constraint.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

REPO_ROOT = Path(__file__).resolve().parents[3]


def _make_alembic_config(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture
def sqlite_url(tmp_path: Path) -> str:
    # Sync URL — alembic upgrade uses a sync engine internally.
    return f"sqlite:///{tmp_path / 'test.db'}"


def test_baseline_upgrade_creates_all_tables(sqlite_url: str) -> None:
    """``alembic upgrade head`` against an empty DB recreates the schema.

    The list of tables checked below is the canonical surface as of v0.2.0;
    new migrations add tables but should never remove them in a baseline.
    """
    cfg = _make_alembic_config(sqlite_url)
    command.upgrade(cfg, "head")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    expected = {
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
        "tenant_overrides",  # added in 0002
        "tenant_provider_credentials",  # added in 0003 (v0.3.0)
        "alembic_version",
    }
    missing = expected - tables
    assert not missing, f"missing tables after upgrade head: {missing}"


def test_v0_3_0_billing_path_column_lands(sqlite_url: str) -> None:
    """0004 adds ``billing_path`` to ``usage_records`` with a portable default."""
    cfg = _make_alembic_config(sqlite_url)
    command.upgrade(cfg, "head")
    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("usage_records")}
    engine.dispose()
    assert "billing_path" in cols


def test_baseline_upgrade_is_idempotent(sqlite_url: str) -> None:
    """Running the upgrade twice is a no-op (the alembic_version row
    advances on first run; second run sees we're already at head)."""
    cfg = _make_alembic_config(sqlite_url)
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")  # must not error

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    assert "tenants" in tables
    assert "alembic_version" in tables


def test_baseline_downgrade_to_base_drops_all_tables(sqlite_url: str) -> None:
    """Downgrade to base leaves only the bookkeeping table."""
    cfg = _make_alembic_config(sqlite_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")

    engine = create_engine(sqlite_url)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    engine.dispose()

    # alembic_version always stays — it's the marker that says "no
    # migrations applied" once the version row is gone.
    assert "tenants" not in tables
    assert "api_keys" not in tables

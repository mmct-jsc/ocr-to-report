"""Alembic migration environment.

Runs migrations either offline (emit SQL to a file) or online (apply
against a live database). We support both sync and async engines —
production runs `make migrate` synchronously, but tests construct a
plain sync URL and skip the asyncio path.

The schema target metadata is imported from the `ocr_to_report.adapters.db`
package so autogenerate sees every ORM model we ship.
"""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Make sure the workspace packages are importable.
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for pkg in ("core", "adapters", "api", "worker", "cli", "sdk_py", "mcp"):
    src = REPO_ROOT / "packages" / pkg / "src"
    if src.exists() and str(src) not in sys.path:
        sys.path.insert(0, str(src))

from ocr_to_report.adapters.db.base import Base  # noqa: E402

# Import every module that defines ORM models so they register themselves
# on Base.metadata before autogenerate inspects it.
import ocr_to_report.adapters.db.models  # noqa: F401, E402

config = context.config

# Allow OCR2R_DATABASE_URL to override the connection string. In tests
# the caller sets sqlalchemy.url programmatically via
# Config.set_main_option() — both paths converge here.
env_url = os.environ.get("OCR2R_DATABASE_URL")
if env_url:
    # asyncpg URLs are fine for the application but alembic itself uses
    # a sync engine. Strip the async dialect prefix when present so the
    # `psycopg` / `psycopg2` driver handles the connection.
    sync_url = env_url.replace("postgresql+asyncpg://", "postgresql://")
    sync_url = sync_url.replace("sqlite+aiosqlite://", "sqlite://")
    config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    try:
        fileConfig(config.config_file_name)
    except KeyError:
        # The minimal alembic.ini we ship may omit logging sections; this
        # is fine — fall back to alembic's defaults.
        pass

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit SQL without a live connection (for ``alembic upgrade --sql``)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against a live DB."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

"""SQLAlchemy 2.0 async session factory + tenant-scoped session helper.

The factory caches engine/sessionmaker instances per database URL so
multiple consumers in the same process share connection pools.

Tenant isolation is layered:

1. **App layer** — repositories filter by ``tenant_id`` (this module).
2. **ORM layer** — :func:`tenant_scoped_session` issues
   ``SET LOCAL app.tenant_id`` on Postgres so RLS policies pick it up.
3. **DB layer** — Phase 5f Postgres RLS policies are the last line of
   defense.

On non-Postgres dialects (SQLite for unit tests) the ``SET LOCAL`` is a
no-op; isolation relies on the app filter only.
"""

from __future__ import annotations

import contextlib
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from ocr_to_report.core.errors.domain import StorageError

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


_ENGINES: dict[str, AsyncEngine] = {}
_SESSIONMAKERS: dict[str, async_sessionmaker[AsyncSession]] = {}


def get_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Return the cached :class:`AsyncEngine` for the URL (creates one if absent)."""
    if url not in _ENGINES:
        _ENGINES[url] = create_async_engine(
            url,
            echo=echo,
            future=True,
            # Reasonable pool defaults; tenants override via env in prod.
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _ENGINES[url]


def get_sessionmaker(url: str, *, echo: bool = False) -> async_sessionmaker[AsyncSession]:
    if url not in _SESSIONMAKERS:
        _SESSIONMAKERS[url] = async_sessionmaker(
            bind=get_engine(url, echo=echo),
            expire_on_commit=False,
            autoflush=False,
        )
    return _SESSIONMAKERS[url]


async def dispose_engines() -> None:
    """Close every cached engine; call on application shutdown."""
    for engine in list(_ENGINES.values()):
        await engine.dispose()
    _ENGINES.clear()
    _SESSIONMAKERS.clear()


@contextlib.asynccontextmanager
async def tenant_scoped_session(
    sm: async_sessionmaker[AsyncSession],
    tenant_id: uuid.UUID,
) -> AsyncIterator[AsyncSession]:
    """Yield an async session bound to a tenant.

    On Postgres, sets ``app.tenant_id`` on the connection so RLS
    policies authored against ``current_setting('app.tenant_id', true)``
    apply automatically. On SQLite this is a no-op.
    """
    session = sm()
    try:
        bind = session.bind
        if bind is not None and bind.dialect.name == "postgresql":
            await session.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
        yield session
        await session.commit()
    except StorageError:
        await session.rollback()
        raise
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


__all__ = [
    "dispose_engines",
    "get_engine",
    "get_sessionmaker",
    "tenant_scoped_session",
]

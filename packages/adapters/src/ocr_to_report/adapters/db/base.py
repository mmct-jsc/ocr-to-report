"""SQLAlchemy declarative base + shared column types.

All ORM models inherit from :class:`Base`. Every row carries
``created_at`` and ``updated_at``; per Decision 4, every tenant-scoped
row also carries ``tenant_id``.

Postgres-specific types (UUID, JSONB) are imported lazily so SQLite
fallbacks (used in fast unit tests) remain functional. The migrations
(Alembic, phase 5d) target Postgres only.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, MetaData, String, TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

if TYPE_CHECKING:
    from sqlalchemy.engine import Dialect


# Cross-dialect UUID column: Postgres native UUID; everything else uses
# CHAR(36). Lets fast unit tests run against SQLite while production
# stays on Postgres.
class GUID(TypeDecorator[uuid.UUID]):
    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import UUID  # noqa: PLC0415

            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return str(uuid.UUID(str(value))) if dialect.name != "postgresql" else uuid.UUID(str(value))

    def process_result_value(self, value: Any, dialect: Dialect) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class JSONB(TypeDecorator[dict[str, Any]]):
    """JSONB on Postgres, JSON on SQLite — same in-memory shape either way."""

    impl = String  # SQLite fallback type; redefined per-dialect below
    cache_ok = True

    def load_dialect_impl(self, dialect: Dialect) -> Any:
        if dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import JSONB as PGJSONB  # noqa: PLC0415

            return dialect.type_descriptor(PGJSONB())
        from sqlalchemy import JSON  # noqa: PLC0415

        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Any, dialect: Dialect) -> Any:
        return value

    def process_result_value(self, value: Any, dialect: Dialect) -> Any:
        return value


# Shared MetaData with explicit naming convention so Alembic produces
# stable, predictable constraint names.
metadata = MetaData(
    naming_convention={
        "ix": "ix_%(column_0_label)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    }
)


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = metadata

    # SQLAlchemy declarative-base convention: this is a class-level dict
    # the ORM machinery reads at class-creation time and never mutates.
    type_annotation_map = {  # noqa: RUF012 — required mapping, never mutated
        uuid.UUID: GUID(),
        dict[str, Any]: JSONB(),
    }


class TimestampedMixin:
    """``created_at`` + ``updated_at`` columns; UTC tz-aware."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


__all__ = ["GUID", "JSONB", "Base", "TimestampedMixin", "metadata"]

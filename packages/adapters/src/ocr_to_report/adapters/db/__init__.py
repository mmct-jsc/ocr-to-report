"""Database layer: SQLAlchemy 2.0 async + Alembic.

Public surface:

* :class:`Base` — declarative base for ORM models.
* Models — every persisted entity (Tenant, ApiKey, Job, etc.).
* :func:`get_engine` / :func:`get_sessionmaker` — cached factories.
* :func:`tenant_scoped_session` — async-context-manager that issues
  ``SET LOCAL app.tenant_id`` on Postgres for RLS.
* Repositories — typed query helpers under :mod:`repositories`.
"""

from ocr_to_report.adapters.db.base import Base, TimestampedMixin
from ocr_to_report.adapters.db.models import (
    ApiKey,
    AuditLog,
    IdempotencyKey,
    Job,
    ResultCacheRow,
    Tenant,
    Transcript,
    UsageRecord,
    Webhook,
)
from ocr_to_report.adapters.db.session import (
    dispose_engines,
    get_engine,
    get_sessionmaker,
    tenant_scoped_session,
)

__all__ = [
    "ApiKey",
    "AuditLog",
    "Base",
    "IdempotencyKey",
    "Job",
    "ResultCacheRow",
    "Tenant",
    "TimestampedMixin",
    "Transcript",
    "UsageRecord",
    "Webhook",
    "dispose_engines",
    "get_engine",
    "get_sessionmaker",
    "tenant_scoped_session",
]

"""Typed repository helpers for the persistence layer.

Each repo is a thin class around an :class:`AsyncSession` that exposes
domain operations and never exposes raw SQLAlchemy types to callers
above. Repos are stateless — construct one per request from the session
factory.
"""

from ocr_to_report.adapters.db.repositories.api_keys import ApiKeyRepo
from ocr_to_report.adapters.db.repositories.audit import AuditRepo
from ocr_to_report.adapters.db.repositories.idempotency import IdempotencyRepo
from ocr_to_report.adapters.db.repositories.jobs import JobRepo
from ocr_to_report.adapters.db.repositories.tenants import TenantRepo
from ocr_to_report.adapters.db.repositories.transcripts import TranscriptRepo
from ocr_to_report.adapters.db.repositories.usage import UsageRepo
from ocr_to_report.adapters.db.repositories.webhooks import WebhookRepo

__all__ = [
    "ApiKeyRepo",
    "AuditRepo",
    "IdempotencyRepo",
    "JobRepo",
    "TenantRepo",
    "TranscriptRepo",
    "UsageRepo",
    "WebhookRepo",
]

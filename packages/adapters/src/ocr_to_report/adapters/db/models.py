"""SQLAlchemy 2.0 declarative ORM models.

Tables shipped in Phase 5 (MVP):

* ``tenants`` — workspace; carries the wrapped DEK, SLA tier, region pin
* ``api_keys`` — Argon2id-hashed credentials with scope list + IP allowlist
* ``webhooks`` — outgoing webhook subscriptions (HMAC-signed delivery)
* ``jobs`` — sync/batch processing state; one row per request
* ``transcripts`` — extracted canonical transcript (encrypted PII column)
* ``audit_log`` — hash-chained tenant audit trail
* ``usage_records`` — per-period token + cost rollups
* ``idempotency_keys`` — 24h replay cache for POST endpoints
* ``result_cache`` — vision-extraction memoization keyed by image hash

Added in v0.2.0:

* ``tenant_overrides`` — per-tenant JSON-patch overrides for pipeline /
  SLA / template / vocabulary, applied by the override resolver at
  request time.

Still deferred to later phases (per Decision 4): ``users`` (JWT auth,
phase 6), ``profile_versions`` / ``target_versions`` / ``templates``
(loaded from disk in MVP — phase 8 adds DB-stored custom bundles).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ocr_to_report.adapters.db.base import JSONB, Base, TimestampedMixin


# ─── tenants ──────────────────────────────────────────────────
class Tenant(Base, TimestampedMixin):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)

    sla_tier: Mapped[str] = mapped_column(String(32), default="standard", nullable=False)
    region_pin: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Envelope-encrypted DEK; destroying this row crypto-shreds every
    # encrypted column for this tenant.
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    profiles_enabled: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    """JSONB: { 'profile_ids': ['pl.lo.swiadectwo_szkolne.v1', ...] }"""

    default_target_system: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_id: Mapped[str] = mapped_column(String(64), default="default_v1", nullable=False)

    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── api_keys ─────────────────────────────────────────────────
class ApiKey(Base, TimestampedMixin):
    __tablename__ = "api_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    # First 8 chars of the key (e.g., 'sk_live_'); for dashboard display.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    # Argon2id-encoded hash of the full key.
    key_hash: Mapped[str] = mapped_column(Text, nullable=False)

    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scopes: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    """JSONB: list of scope strings, e.g., ['transcripts:write']."""

    ip_allowlist: Mapped[dict[str, Any] | None] = mapped_column(nullable=True)
    """JSONB list of CIDR strings."""

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_api_keys_tenant_id", "tenant_id"),
        Index("ix_api_keys_prefix", "prefix"),
    )


# ─── webhooks ─────────────────────────────────────────────────
class Webhook(Base, TimestampedMixin):
    __tablename__ = "webhooks"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # The signing secret, encrypted with the tenant DEK (so a DB dump
    # leak doesn't expose webhook secrets).
    secret_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    events: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    """JSONB list of event types this webhook subscribes to."""
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    last_delivery_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_webhooks_tenant_id", "tenant_id"),)


# ─── jobs ─────────────────────────────────────────────────────
class Job(Base, TimestampedMixin):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    """One of: pending, running, parked, succeeded, failed, cancelled."""
    kind: Mapped[str] = mapped_column(String(32), default="sync", nullable=False)
    """sync | batch."""

    profile_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_template_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pipeline_id: Mapped[str] = mapped_column(String(64), default="default_v1", nullable=False)

    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)

    provider_used: Mapped[str | None] = mapped_column(String(32), nullable=True)
    model_id_used: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usd_cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)

    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    park_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    input_blob_key: Mapped[str | None] = mapped_column(String(256), nullable=True)
    output_blob_key: Mapped[str | None] = mapped_column(String(256), nullable=True)

    webhook_status: Mapped[str | None] = mapped_column(String(32), nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When this job's blobs + transcript should be purged (retention)."""

    __table_args__ = (
        Index("ix_jobs_tenant_id", "tenant_id"),
        Index("ix_jobs_status", "status"),
        UniqueConstraint(
            "tenant_id",
            "idempotency_key",
            name="uq_jobs_tenant_idempotency",
        ),
    )


# ─── transcripts ──────────────────────────────────────────────
class Transcript(Base, TimestampedMixin):
    __tablename__ = "transcripts"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    job_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )

    # SHA-256 of the preprocessed input (lookup + dedup).
    input_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    output_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # CanonicalTranscript serialized + encrypted with the tenant DEK.
    canonical_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    overall_confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)

    __table_args__ = (
        Index("ix_transcripts_tenant_id", "tenant_id"),
        Index("ix_transcripts_input_sha256", "tenant_id", "input_sha256"),
    )


# ─── audit_log ────────────────────────────────────────────────
class AuditLog(Base):
    """Append-only hash-chained audit trail.

    No ``updated_at`` — rows are immutable. The chain integrity (per
    tenant) is maintained by the audit writer using
    :func:`adapters.audit.next_entry`; the verifier cron walks each
    tenant's chain in chronological order.
    """

    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    """api_key | jwt | system"""
    actor_id_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 of the actor id; never the raw id."""

    action: Mapped[str] = mapped_column(String(120), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(120), nullable=True)

    ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    """JSONB. Must NOT contain raw PII (only hashes / non-PII metadata)."""

    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        Index("ix_audit_log_tenant_ts", "tenant_id", "ts"),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
    )


# ─── usage_records ────────────────────────────────────────────
class UsageRecord(Base, TimestampedMixin):
    __tablename__ = "usage_records"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    transcripts_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_input: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    tokens_output: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    usd_cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "period_start",
            "period_end",
            name="uq_usage_tenant_period",
        ),
    )


# ─── idempotency_keys ─────────────────────────────────────────
class IdempotencyKey(Base, TimestampedMixin):
    __tablename__ = "idempotency_keys"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    key: Mapped[str] = mapped_column(String(128), nullable=False)
    # request_hash holds ``<sha256>:<profile_id>:<target_id>`` so the
    # idempotency replay only fires for the exact same request shape.
    # 64 chars (sha) + 2 separators + ~120 chars of ids — round up.
    request_hash: Mapped[str] = mapped_column(String(256), nullable=False)

    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    response_content_type: Mapped[str] = mapped_column(String(120), nullable=False)

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "key",
            name="uq_idempotency_tenant_key",
        ),
    )


# ─── result_cache ─────────────────────────────────────────────
class ResultCacheRow(Base, TimestampedMixin):
    """Vision extraction result memo, keyed by preprocessed-image hash."""

    __tablename__ = "result_cache"

    key: Mapped[str] = mapped_column(String(256), primary_key=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
    )
    """Optional: scope cache per-tenant when isolation matters more than dedup."""
    result_blob: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# ─── batch_submissions ────────────────────────────────────────
class BatchSubmission(Base, TimestampedMixin):
    """An in-flight Anthropic Batch API submission.

    A single row tracks a provider batch and the set of jobs it covers.
    The worker's BATCH_POLL handler walks active rows and reconciles
    results back into job rows when the batch ends.
    """

    __tablename__ = "batch_submissions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(String(32), default="anthropic", nullable=False)
    """Stable provider id (e.g., 'anthropic')."""

    batch_id: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    """Provider-assigned batch id."""

    job_ids: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    """JSONB: list of job_id strings included in this batch."""

    status: Mapped[str] = mapped_column(String(32), default="in_progress", nullable=False)
    """One of: in_progress, ended, canceled, expired, errored."""

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_batch_submissions_tenant_status", "tenant_id", "status"),)


# ─── tenant_overrides ─────────────────────────────────────────
class TenantOverride(Base, TimestampedMixin):
    """Per-tenant JSON-patch overrides on the universal bundle dicts.

    Each row carries a list of override patches scoped to one of:

    * ``scope='pipeline'`` — patches against the resolved pipeline yaml
      (e.g., swap pipeline id, tweak step config). ``target_id`` is NULL.
    * ``scope='sla'`` — patches against the tenant's SLA tier preset
      (e.g., raise ``confidence_threshold``). ``target_id`` is NULL.
    * ``scope='profile'`` — patches against the source profile bundle's
      vocabulary / grade scale / year system. ``target_id`` is the
      profile id.
    * ``scope='target'`` — patches against a target bundle's manifest /
      taxonomy. ``target_id`` is the target id.
    * ``scope='template'`` — patches that point a template key at a
      tenant-uploaded xlsx blob. ``target_id`` is the target id.

    The unique constraint on ``(tenant_id, scope, target_id)`` makes
    upsert by triple the natural primitive; v0.2.0 ships only one row
    per scope+target, future versions can grow this with versioning if
    needed.

    The patch dicts validate against
    ``core.overrides.resolver.OverridePatch`` when applied — invalid
    patches surface as ``OverrideError`` (HTTP 400) at request time.
    """

    __tablename__ = "tenant_overrides"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
    )
    scope: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # ``list[dict]`` isn't in the type_annotation_map so we bind the
    # JSONB TypeDecorator explicitly. On Postgres this is native JSONB;
    # on SQLite it's JSON.
    patches: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB(),
        default=list,
        nullable=False,
    )
    """JSONB list of ``{op, path, value}`` documents."""

    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "scope",
            "target_id",
            name="uq_tenant_overrides_scope",
        ),
        Index(
            "ix_tenant_overrides_lookup",
            "tenant_id",
            "scope",
            "enabled",
        ),
    )


__all__ = [
    "ApiKey",
    "AuditLog",
    "BatchSubmission",
    "IdempotencyKey",
    "Job",
    "ResultCacheRow",
    "Tenant",
    "TenantOverride",
    "Transcript",
    "UsageRecord",
    "Webhook",
]

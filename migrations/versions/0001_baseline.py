"""baseline — phase 5 schema

Revision ID: 0001
Revises:
Create Date: 2026-04-29

The first real migration. Encodes the Phase-5 schema that the test
suite + dev compose were previously creating via
``Base.metadata.create_all``. Future migrations are additive on top of
this baseline (next up: ``0002_tenant_overrides``).

We use ``sa.String(36)`` for UUID columns and ``sa.JSON`` for JSONB
columns so the migration runs on both SQLite (test) and Postgres
(production). The ORM-side ``GUID`` / ``JSONB`` TypeDecorators in
``ocr_to_report.adapters.db.base`` map onto these underlying column
types per-dialect automatically; production gets native UUID + JSONB,
tests get String(36) + JSON.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Postgres-native column types when running on Postgres; sane portable
# fallbacks elsewhere. Concentrating the choice here keeps every
# table-create below identical.
def _uuid_col() -> sa.types.TypeEngine:
    return sa.String(36)


def _json_col() -> sa.types.TypeEngine:
    return sa.JSON()


def _ts(tz: bool = True) -> sa.types.TypeEngine:
    return sa.DateTime(timezone=tz)


def upgrade() -> None:
    # ─── tenants ──────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(120), nullable=False),
        sa.Column("sla_tier", sa.String(32), nullable=False, server_default="standard"),
        sa.Column("region_pin", sa.String(64), nullable=True),
        sa.Column("dek_wrapped", sa.LargeBinary, nullable=False),
        sa.Column("profiles_enabled", _json_col(), nullable=False),
        sa.Column("default_target_system", sa.String(64), nullable=True),
        sa.Column("pipeline_id", sa.String(64), nullable=False, server_default="default_v1"),
        sa.Column("archived_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenants"),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    # ─── api_keys ─────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.Text, nullable=False),
        sa.Column("label", sa.String(120), nullable=True),
        sa.Column("scopes", _json_col(), nullable=False),
        sa.Column("ip_allowlist", _json_col(), nullable=True),
        sa.Column("expires_at", _ts(), nullable=True),
        sa.Column("revoked_at", _ts(), nullable=True),
        sa.Column("last_used_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_api_keys_tenant_id_tenants",
        ),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_prefix", "api_keys", ["prefix"])

    # ─── webhooks ─────────────────────────────────────────────
    op.create_table(
        "webhooks",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("secret_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("events", _json_col(), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("last_delivery_status", sa.String(32), nullable=True),
        sa.Column("last_delivered_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_webhooks"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_webhooks_tenant_id_tenants",
        ),
    )
    op.create_index("ix_webhooks_tenant_id", "webhooks", ["tenant_id"])

    # ─── jobs ─────────────────────────────────────────────────
    op.create_table(
        "jobs",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("kind", sa.String(32), nullable=False, server_default="sync"),
        sa.Column("profile_id", sa.String(128), nullable=True),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("target_template_key", sa.String(64), nullable=True),
        sa.Column("pipeline_id", sa.String(64), nullable=False, server_default="default_v1"),
        sa.Column("idempotency_key", sa.String(128), nullable=True),
        sa.Column("provider_used", sa.String(32), nullable=True),
        sa.Column("model_id_used", sa.String(128), nullable=True),
        sa.Column("tokens_input", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd_cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("error_detail", sa.Text, nullable=True),
        sa.Column("park_reason", sa.Text, nullable=True),
        sa.Column("input_blob_key", sa.String(256), nullable=True),
        sa.Column("output_blob_key", sa.String(256), nullable=True),
        sa.Column("webhook_status", sa.String(32), nullable=True),
        sa.Column("completed_at", _ts(), nullable=True),
        sa.Column("expires_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_jobs_tenant_id_tenants",
        ),
        sa.UniqueConstraint(
            "tenant_id", "idempotency_key", name="uq_jobs_tenant_idempotency",
        ),
    )
    op.create_index("ix_jobs_tenant_id", "jobs", ["tenant_id"])
    op.create_index("ix_jobs_status", "jobs", ["status"])

    # ─── transcripts ──────────────────────────────────────────
    op.create_table(
        "transcripts",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("job_id", _uuid_col(), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("output_sha256", sa.String(64), nullable=True),
        sa.Column("canonical_encrypted", sa.LargeBinary, nullable=False),
        sa.Column("overall_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_transcripts"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_transcripts_tenant_id_tenants",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["jobs.id"],
            ondelete="CASCADE", name="fk_transcripts_job_id_jobs",
        ),
        sa.UniqueConstraint("job_id", name="uq_transcripts_job_id"),
    )
    op.create_index("ix_transcripts_tenant_id", "transcripts", ["tenant_id"])
    op.create_index(
        "ix_transcripts_input_sha256", "transcripts", ["tenant_id", "input_sha256"],
    )

    # ─── audit_log ────────────────────────────────────────────
    op.create_table(
        "audit_log",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("ts", _ts(), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id_hash", sa.String(64), nullable=False),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(120), nullable=True),
        sa.Column("ip", sa.String(64), nullable=True),
        sa.Column("user_agent_hash", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
        sa.Column("metadata_json", _json_col(), nullable=False),
        sa.Column("prev_hash", sa.String(64), nullable=False),
        sa.Column("row_hash", sa.String(64), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_log"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_audit_log_tenant_id_tenants",
        ),
        sa.UniqueConstraint("row_hash", name="uq_audit_log_row_hash"),
    )
    op.create_index("ix_audit_log_tenant_ts", "audit_log", ["tenant_id", "ts"])
    op.create_index(
        "ix_audit_log_resource", "audit_log", ["resource_type", "resource_id"],
    )

    # ─── usage_records ────────────────────────────────────────
    op.create_table(
        "usage_records",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("period_start", _ts(), nullable=False),
        sa.Column("period_end", _ts(), nullable=False),
        sa.Column("transcripts_processed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_input", sa.Integer, nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("cache_creation_tokens", sa.Integer, nullable=False, server_default="0"),
        sa.Column("usd_cost", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_usage_records"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_usage_records_tenant_id_tenants",
        ),
        sa.UniqueConstraint(
            "tenant_id", "period_start", "period_end", name="uq_usage_tenant_period",
        ),
    )

    # ─── idempotency_keys ─────────────────────────────────────
    op.create_table(
        "idempotency_keys",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(256), nullable=False),
        sa.Column("response_status", sa.Integer, nullable=False),
        sa.Column("response_body", sa.LargeBinary, nullable=False),
        sa.Column("response_content_type", sa.String(120), nullable=False),
        sa.Column("expires_at", _ts(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_keys"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_idempotency_keys_tenant_id_tenants",
        ),
        sa.UniqueConstraint("tenant_id", "key", name="uq_idempotency_tenant_key"),
    )

    # ─── result_cache ─────────────────────────────────────────
    op.create_table(
        "result_cache",
        sa.Column("key", sa.String(256), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=True),
        sa.Column("result_blob", sa.LargeBinary, nullable=False),
        sa.Column("expires_at", _ts(), nullable=False),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("key", name="pk_result_cache"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE", name="fk_result_cache_tenant_id_tenants",
        ),
    )

    # ─── batch_submissions ────────────────────────────────────
    op.create_table(
        "batch_submissions",
        sa.Column("id", _uuid_col(), nullable=False),
        sa.Column("tenant_id", _uuid_col(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="anthropic"),
        sa.Column("batch_id", sa.String(120), nullable=False),
        sa.Column("job_ids", _json_col(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="in_progress"),
        sa.Column("submitted_at", _ts(), nullable=False),
        sa.Column("last_polled_at", _ts(), nullable=True),
        sa.Column("completed_at", _ts(), nullable=True),
        sa.Column("created_at", _ts(), nullable=False),
        sa.Column("updated_at", _ts(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_batch_submissions"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_batch_submissions_tenant_id_tenants",
        ),
        sa.UniqueConstraint("batch_id", name="uq_batch_submissions_batch_id"),
    )
    op.create_index(
        "ix_batch_submissions_tenant_status",
        "batch_submissions",
        ["tenant_id", "status"],
    )


def downgrade() -> None:
    # Reverse-creation order to satisfy FK constraints.
    op.drop_index("ix_batch_submissions_tenant_status", table_name="batch_submissions")
    op.drop_table("batch_submissions")
    op.drop_table("result_cache")
    op.drop_table("idempotency_keys")
    op.drop_table("usage_records")
    op.drop_index("ix_audit_log_resource", table_name="audit_log")
    op.drop_index("ix_audit_log_tenant_ts", table_name="audit_log")
    op.drop_table("audit_log")
    op.drop_index("ix_transcripts_input_sha256", table_name="transcripts")
    op.drop_index("ix_transcripts_tenant_id", table_name="transcripts")
    op.drop_table("transcripts")
    op.drop_index("ix_jobs_status", table_name="jobs")
    op.drop_index("ix_jobs_tenant_id", table_name="jobs")
    op.drop_table("jobs")
    op.drop_index("ix_webhooks_tenant_id", table_name="webhooks")
    op.drop_table("webhooks")
    op.drop_index("ix_api_keys_prefix", table_name="api_keys")
    op.drop_index("ix_api_keys_tenant_id", table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("tenants")

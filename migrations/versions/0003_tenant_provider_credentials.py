"""tenant_provider_credentials — per-tenant BYOK storage

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-21

Introduces ``tenant_provider_credentials``, the storage layer for
v0.3.0's Bring-Your-Own-Key flow. Each row holds one envelope-encrypted
API key for one ``(tenant, provider)`` pair. The ``active`` column plus
a partial unique index (``WHERE active = TRUE``) gives us cheap rotation
history: marking the old row inactive in the same transaction that
inserts the new one preserves a full audit trail while keeping exactly
one credential routable per provider at any time.

``model_overrides`` and ``region`` ship as columns but are not consumed
in v0.3.0 — v0.7.0 (provider expansion) reads model overrides, v0.6.0
gates EU/region tenants on the region pin. Shipping the columns now
saves a follow-up migration.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, Sequence[str], None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_provider_credentials",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        # text rather than enum: SQLite + Postgres both treat this as
        # a small string; the application layer pins the legal set.
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("encrypted_api_key", sa.LargeBinary, nullable=False),
        sa.Column(
            "model_overrides",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("region", sa.String(64), nullable=True),
        sa.Column(
            "active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_provider_credentials"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_tenant_provider_credentials_tenant_id_tenants",
        ),
    )

    # Partial unique index. Postgres uses ``WHERE active = TRUE``; SQLite
    # accepts the same with ``active = 1`` because its booleans are
    # integers. The dialect-keyed arguments below are mutually exclusive
    # in practice — alembic emits whichever the target backend supports.
    op.create_index(
        "ix_tenant_provider_credentials_active",
        "tenant_provider_credentials",
        ["tenant_id", "provider"],
        unique=True,
        postgresql_where=sa.text("active = TRUE"),
        sqlite_where=sa.text("active = 1"),
    )
    # Broad lookup index (active credential scan by tenant).
    op.create_index(
        "ix_tenant_provider_credentials_lookup",
        "tenant_provider_credentials",
        ["tenant_id", "provider", "active"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_tenant_provider_credentials_lookup",
        table_name="tenant_provider_credentials",
    )
    op.drop_index(
        "ix_tenant_provider_credentials_active",
        table_name="tenant_provider_credentials",
    )
    op.drop_table("tenant_provider_credentials")

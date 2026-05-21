"""tenant_overrides — per-tenant JSON-patch storage

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-29

Introduces the ``tenant_overrides`` table, the storage layer for the
override resolver. One row per ``(tenant_id, scope, target_id)``
triple, where ``scope`` is one of: ``pipeline``, ``sla``, ``profile``,
``target``, ``template``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tenant_overrides",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(120), nullable=True),
        # Stored as JSON; the ORM-side JSONB TypeDecorator surfaces it
        # as the dialect-native type (JSONB on Postgres, JSON on SQLite).
        sa.Column("patches", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_tenant_overrides"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["tenants.id"],
            ondelete="CASCADE",
            name="fk_tenant_overrides_tenant_id_tenants",
        ),
        sa.UniqueConstraint(
            "tenant_id", "scope", "target_id",
            name="uq_tenant_overrides_scope",
        ),
    )
    op.create_index(
        "ix_tenant_overrides_lookup",
        "tenant_overrides",
        ["tenant_id", "scope", "enabled"],
    )


def downgrade() -> None:
    op.drop_index("ix_tenant_overrides_lookup", table_name="tenant_overrides")
    op.drop_table("tenant_overrides")

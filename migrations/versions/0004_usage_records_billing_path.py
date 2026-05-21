"""usage_records.billing_path — split platform-billed vs BYOK usage

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-21

Adds ``billing_path`` to ``usage_records``. Required for v0.4.0
invoicing to ignore BYOK rows: a BYOK tenant's vision calls hit their
own Anthropic account, so the platform must not include those tokens
on its bill.

Backfill: every pre-existing row was platform-billed by definition,
so the column is created NOT NULL with a server default of
``'platform'`` and the backfill is implicit (postgres applies the
default when adding a NOT NULL column without an explicit value).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, Sequence[str], None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ``batch_alter_table`` is required so SQLite's no-ALTER limitation
    # is handled via copy-and-move; Postgres treats it as a normal
    # ALTER TABLE.
    with op.batch_alter_table("usage_records") as batch_op:
        batch_op.add_column(
            sa.Column(
                "billing_path",
                sa.String(16),
                nullable=False,
                server_default="platform",
            ),
        )
        batch_op.create_check_constraint(
            "ck_usage_records_billing_path",
            "billing_path IN ('platform', 'byok')",
        )


def downgrade() -> None:
    with op.batch_alter_table("usage_records") as batch_op:
        batch_op.drop_constraint(
            "ck_usage_records_billing_path",
            type_="check",
        )
        batch_op.drop_column("billing_path")

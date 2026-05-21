"""UsageRepo — per-period token + cost rollups.

Rows are keyed on ``(tenant_id, period_start, period_end, billing_path)``
so platform-billed and BYOK-billed usage roll up to SEPARATE rows. The
``billing_path`` discriminator (added v0.3.0) lets v0.4.0 invoicing
include ``billing_path = 'platform'`` rows only — BYOK usage was billed
to the tenant's own provider account, not the platform.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import UsageRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class UsageRepo:
    """Repository for the ``usage_records`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def increment(
        self,
        *,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        transcripts: int = 0,
        tokens_input: int = 0,
        tokens_output: int = 0,
        cache_read_tokens: int = 0,
        cache_creation_tokens: int = 0,
        usd_cost: float = 0.0,
        billing_path: str = "platform",
    ) -> UsageRecord:
        """Increment the rollup for the given period + billing path.

        ``billing_path`` defaults to ``'platform'`` so every existing
        call site continues working unchanged. A BYOK request rolls up
        to a separate row by passing ``billing_path='byok'``."""
        result = await self._session.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.period_start == period_start,
                UsageRecord.period_end == period_end,
                UsageRecord.billing_path == billing_path,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = UsageRecord(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
                transcripts_processed=transcripts,
                tokens_input=tokens_input,
                tokens_output=tokens_output,
                cache_read_tokens=cache_read_tokens,
                cache_creation_tokens=cache_creation_tokens,
                usd_cost=usd_cost,
                billing_path=billing_path,
            )
            self._session.add(row)
        else:
            row.transcripts_processed += transcripts
            row.tokens_input += tokens_input
            row.tokens_output += tokens_output
            row.cache_read_tokens += cache_read_tokens
            row.cache_creation_tokens += cache_creation_tokens
            row.usd_cost = float(row.usd_cost) + usd_cost
        await self._session.flush()
        return row

    async def get_period(
        self,
        *,
        tenant_id: uuid.UUID,
        period_start: datetime,
        period_end: datetime,
        billing_path: str = "platform",
    ) -> UsageRecord | None:
        """Look up a single rollup row by ``(tenant, period, billing_path)``.

        Defaults to the ``'platform'`` row — that's the relevant one for
        invoicing. Callers that want the BYOK row pass it explicitly.
        """
        result = await self._session.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.period_start == period_start,
                UsageRecord.period_end == period_end,
                UsageRecord.billing_path == billing_path,
            )
        )
        return result.scalar_one_or_none()


__all__ = ["UsageRepo"]

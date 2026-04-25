"""UsageRepo — per-period token + cost rollups."""

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
    ) -> UsageRecord:
        result = await self._session.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.period_start == period_start,
                UsageRecord.period_end == period_end,
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
    ) -> UsageRecord | None:
        result = await self._session.execute(
            select(UsageRecord).where(
                UsageRecord.tenant_id == tenant_id,
                UsageRecord.period_start == period_start,
                UsageRecord.period_end == period_end,
            )
        )
        return result.scalar_one_or_none()


__all__ = ["UsageRepo"]

"""BatchSubmissionRepo — track in-flight Anthropic batches per tenant."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import BatchSubmission

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class BatchSubmissionRepo:
    """Repository for the ``batch_submissions`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
        batch_id: str,
        job_ids: list[str],
        submitted_at: datetime,
    ) -> BatchSubmission:
        row = BatchSubmission(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            batch_id=batch_id,
            job_ids={"ids": job_ids},
            status="in_progress",
            submitted_at=submitted_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def get(self, submission_id: uuid.UUID) -> BatchSubmission | None:
        return await self._session.get(BatchSubmission, submission_id)

    async def get_by_batch_id(self, batch_id: str) -> BatchSubmission | None:
        result = await self._session.execute(
            select(BatchSubmission).where(BatchSubmission.batch_id == batch_id)
        )
        return result.scalar_one_or_none()

    async def list_in_progress(
        self,
        *,
        tenant_id: uuid.UUID | None = None,
    ) -> list[BatchSubmission]:
        stmt = select(BatchSubmission).where(BatchSubmission.status == "in_progress")
        if tenant_id is not None:
            stmt = stmt.where(BatchSubmission.tenant_id == tenant_id)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def mark_polled(self, submission_id: uuid.UUID) -> None:
        row = await self._session.get(BatchSubmission, submission_id)
        if row is None:
            return
        row.last_polled_at = datetime.now(tz=UTC)

    async def mark_completed(self, submission_id: uuid.UUID, *, status: str) -> None:
        row = await self._session.get(BatchSubmission, submission_id)
        if row is None:
            return
        row.status = status
        row.completed_at = datetime.now(tz=UTC)


__all__ = ["BatchSubmissionRepo"]

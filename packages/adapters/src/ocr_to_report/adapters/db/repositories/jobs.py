"""JobRepo — sync/batch processing-state lifecycle."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import Job

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class JobRepo:
    """Repository for the ``jobs`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        kind: str = "sync",
        profile_id: str | None = None,
        target_id: str | None = None,
        target_template_key: str | None = None,
        pipeline_id: str = "default_v1",
        idempotency_key: str | None = None,
        input_blob_key: str | None = None,
        expires_at: datetime | None = None,
    ) -> Job:
        job = Job(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            kind=kind,
            profile_id=profile_id,
            target_id=target_id,
            target_template_key=target_template_key,
            pipeline_id=pipeline_id,
            idempotency_key=idempotency_key,
            input_blob_key=input_blob_key,
            expires_at=expires_at,
        )
        self._session.add(job)
        await self._session.flush()
        return job

    async def get(self, job_id: uuid.UUID) -> Job | None:
        return await self._session.get(Job, job_id)

    async def get_by_idempotency(
        self,
        tenant_id: uuid.UUID,
        idempotency_key: str,
    ) -> Job | None:
        result = await self._session.execute(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        return result.scalar_one_or_none()

    async def mark_running(self, job_id: uuid.UUID) -> None:
        job = await self._session.get(Job, job_id)
        if job is None:
            return
        job.status = "running"

    async def mark_succeeded(
        self,
        job_id: uuid.UUID,
        *,
        output_blob_key: str,
        provider_used: str,
        model_id_used: str,
        tokens_input: int,
        tokens_output: int,
        usd_cost: float,
    ) -> None:
        job = await self._session.get(Job, job_id)
        if job is None:
            return
        job.status = "succeeded"
        job.output_blob_key = output_blob_key
        job.provider_used = provider_used
        job.model_id_used = model_id_used
        job.tokens_input = tokens_input
        job.tokens_output = tokens_output
        job.usd_cost = usd_cost
        job.completed_at = datetime.now(tz=UTC)

    async def mark_failed(self, job_id: uuid.UUID, *, error_detail: str) -> None:
        job = await self._session.get(Job, job_id)
        if job is None:
            return
        job.status = "failed"
        job.error_detail = error_detail
        job.completed_at = datetime.now(tz=UTC)

    async def mark_parked(self, job_id: uuid.UUID, *, park_reason: str) -> None:
        job = await self._session.get(Job, job_id)
        if job is None:
            return
        job.status = "parked"
        job.park_reason = park_reason

    async def list_expired(self, *, now: datetime | None = None, limit: int = 100) -> list[Job]:
        cutoff = now or datetime.now(tz=UTC)
        result = await self._session.execute(
            select(Job).where(Job.expires_at.is_not(None), Job.expires_at < cutoff).limit(limit)
        )
        return list(result.scalars().all())


__all__ = ["JobRepo"]

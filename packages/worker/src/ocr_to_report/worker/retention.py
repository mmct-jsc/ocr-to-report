"""Retention service — purge expired job artifacts.

Runs from inside the worker (triggered by ``RETENTION_SWEEP`` tasks) but
is also callable from a CLI cron entrypoint without going through the
queue. The two callers share this single implementation so behavior is
identical regardless of trigger.

What gets purged when a job's ``expires_at`` falls in the past:

1. The output blob (xlsx) at ``output_blob_key``.
2. The input blob at ``input_blob_key``.
3. The encrypted ``Transcript`` row.
4. An audit-log entry recording the purge.
5. The ``Job`` row itself (last, to preserve referential integrity).

The purge is per-tenant: pass a tenant_id when invoking from the cron to
serialize sweeps; in production we run them per-tenant on a staggered
schedule to avoid storage bursts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from ocr_to_report.adapters.db.repositories import (
    AuditRepo,
    JobRepo,
    TranscriptRepo,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from ocr_to_report.adapters.blob import BlobStore
    from ocr_to_report.adapters.crypto import EnvelopeEncryptor


@dataclass(frozen=True, slots=True)
class RetentionReport:
    """Aggregate result of a single retention sweep run."""

    sweep_started_at: datetime
    sweep_finished_at: datetime
    jobs_inspected: int
    jobs_purged: int
    blobs_deleted: int
    errors: list[str]


class RetentionService:
    """Idempotent expired-job purger.

    Args:
        sessionmaker: Async sessionmaker for the worker process.
        blob_store: Where the input + output blobs live.
        encryptor: Required by the audit / transcript repos but not
            actually needed for the purge path (no decryption happens).
    """

    def __init__(
        self,
        *,
        sessionmaker: async_sessionmaker[AsyncSession],
        blob_store: BlobStore,
        encryptor: EnvelopeEncryptor,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._blob_store = blob_store
        self._encryptor = encryptor

    async def sweep(self, *, limit: int = 100) -> RetentionReport:
        """Purge up to ``limit`` expired jobs across all tenants."""
        started = datetime.now(tz=UTC)
        errors: list[str] = []
        jobs_purged = 0
        blobs_deleted = 0

        async with self._sessionmaker() as session:
            jobs_repo = JobRepo(session)
            expired = await jobs_repo.list_expired(now=started, limit=limit)

        # Process one job per session so a single failing purge doesn't
        # roll back the others. The DB row is the source of truth — we
        # only touch blobs after the row delete commits.
        for job in expired:
            try:
                deleted_blobs = await self._purge_one(
                    job_id=job.id,
                    tenant_id=job.tenant_id,
                    input_blob_key=job.input_blob_key,
                    output_blob_key=job.output_blob_key,
                )
                jobs_purged += 1
                blobs_deleted += deleted_blobs
            except Exception as e:
                errors.append(f"job {job.id}: {type(e).__name__}: {e}")

        finished = datetime.now(tz=UTC)
        return RetentionReport(
            sweep_started_at=started,
            sweep_finished_at=finished,
            jobs_inspected=len(expired),
            jobs_purged=jobs_purged,
            blobs_deleted=blobs_deleted,
            errors=errors,
        )

    async def _purge_one(
        self,
        *,
        job_id: uuid.UUID,
        tenant_id: uuid.UUID,
        input_blob_key: str | None,
        output_blob_key: str | None,
    ) -> int:
        """Atomically purge one job + its artifacts. Returns blob-delete count."""
        async with self._sessionmaker() as session:
            transcripts_repo = TranscriptRepo(session, self._encryptor)
            audit_repo = AuditRepo(session)
            jobs_repo = JobRepo(session)

            await transcripts_repo.delete_by_job(tenant_id=tenant_id, job_id=job_id)
            await audit_repo.append(
                tenant_id=tenant_id,
                actor_type="system",
                actor_id_hash="",
                action="job.retention_purged",
                resource_type="job",
                resource_id=str(job_id),
            )
            await jobs_repo.delete(job_id)
            await session.commit()

        # Now that the row is gone, drop the blobs. If blob deletion
        # fails, the next sweep won't re-attempt — but the job row is
        # already gone, so we accept a small chance of orphaned blobs
        # in exchange for never blocking a purge on storage flakes.
        import logging  # noqa: PLC0415

        log = logging.getLogger("ocr_to_report.worker.retention")

        deleted = 0
        for key in (input_blob_key, output_blob_key):
            if key is None:
                continue
            try:
                await self._blob_store.delete(key)
                deleted += 1
            except Exception as e:
                log.warning(
                    "blob delete failed during retention purge",
                    extra={"key": key, "error": f"{type(e).__name__}: {e}"},
                )
        return deleted


__all__ = ["RetentionReport", "RetentionService"]

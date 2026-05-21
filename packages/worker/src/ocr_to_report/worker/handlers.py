"""Worker task handlers.

Each handler corresponds to one :class:`TaskKind`. Handlers are async,
side-effecting, and idempotent enough that re-delivery (after a crash
mid-execution) does not cause duplicate work — they re-check job/batch
state from the DB before mutating.

The runner dispatches to these by ``kind``; failures are translated into
nacks with backoff. Handlers MUST NOT swallow exceptions — let them
propagate so the runner can record the failure and re-queue.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ocr_to_report.adapters.db import get_sessionmaker
from ocr_to_report.adapters.db.repositories import (
    AuditRepo,
    BatchSubmissionRepo,
    JobRepo,
    TenantRepo,
    UsageRepo,
)
from ocr_to_report.adapters.queue import TaskEnvelope, TaskKind
from ocr_to_report.adapters.vision import (
    BatchStatus,
    VisionRequest,
    compile_schema,
)
from ocr_to_report.core.errors.domain import (
    ProfileNotFoundError,
    VisionProviderError,
)

if TYPE_CHECKING:
    from ocr_to_report.adapters.db.models import Job
    from ocr_to_report.worker.context import WorkerContext


# ─── BATCH_SUBMIT ────────────────────────────────────────────
async def handle_batch_submit(ctx: WorkerContext, envelope: TaskEnvelope) -> None:
    """Bundle pending batch jobs for a tenant + submit to the provider.

    Payload: ``{"tenant_id": "<uuid>"}``.

    Steps:

    1. Look up pending batch-kind jobs for the tenant (up to 100).
    2. Read each job's input blob.
    3. Build a :class:`VisionRequest` per job.
    4. Submit the bundle via :class:`AnthropicBatchAdapter`.
    5. Persist a :class:`BatchSubmission` row with the provider batch_id.
    6. Mark each job ``running``.
    7. Schedule a BATCH_POLL task for the new submission.
    """
    if ctx.batch_adapter is None:
        raise VisionProviderError(
            "no batch adapter configured (ANTHROPIC_API_KEY unset)",
            kind=envelope.kind.value,
        )

    tenant_id = uuid.UUID(envelope.payload["tenant_id"])
    sm = get_sessionmaker(ctx.settings.database_url)

    async with sm() as session:
        jobs_repo = JobRepo(session)
        pending = await jobs_repo.list_pending_batch(tenant_id=tenant_id, limit=100)

    if not pending:
        return

    requests: list[tuple[str, VisionRequest]] = []
    valid_jobs: list[Job] = []
    for job in pending:
        try:
            req = await _build_vision_request(ctx, job)
        except (ProfileNotFoundError, KeyError, ValueError) as e:
            async with sm() as session:
                fail_repo = JobRepo(session)
                await fail_repo.mark_failed(job.id, error_detail=f"batch prep: {e}")
                await session.commit()
            continue
        requests.append((str(job.id), req))
        valid_jobs.append(job)

    if not requests:
        return

    handle = await ctx.batch_adapter.submit(requests)

    async with sm() as session:
        sub_repo = BatchSubmissionRepo(session)
        await sub_repo.create(
            tenant_id=tenant_id,
            provider="anthropic",
            batch_id=handle.batch_id,
            job_ids=[str(j.id) for j in valid_jobs],
            submitted_at=handle.submitted_at,
        )
        jobs_repo = JobRepo(session)
        for job in valid_jobs:
            await jobs_repo.mark_running(job.id)
        audit = AuditRepo(session)
        await audit.append(
            tenant_id=tenant_id,
            actor_type="system",
            actor_id_hash="",
            action="batch.submitted",
            resource_type="batch",
            resource_id=handle.batch_id,
            metadata={"job_count": len(valid_jobs)},
        )
        await session.commit()

    await ctx.queue.enqueue(
        TaskKind.BATCH_POLL,
        {"batch_id": handle.batch_id, "tenant_id": str(tenant_id)},
        tenant_id=tenant_id,
        delay_seconds=300.0,  # 5 min — typical batch SLA is hours
    )


# ─── BATCH_POLL ──────────────────────────────────────────────
async def handle_batch_poll(ctx: WorkerContext, envelope: TaskEnvelope) -> None:
    """Poll a submitted batch; on completion, fan results into job rows.

    Payload: ``{"batch_id": "<provider-id>", "tenant_id": "<uuid>"}``.

    If the batch is still in_progress, re-enqueue with exponential
    backoff (capped at 30 minutes). When ended, fetch results and
    update each job to succeeded/failed; mark the submission completed.
    """
    if ctx.batch_adapter is None:
        raise VisionProviderError(
            "no batch adapter configured (ANTHROPIC_API_KEY unset)",
            kind=envelope.kind.value,
        )

    batch_id = envelope.payload["batch_id"]
    tenant_id = uuid.UUID(envelope.payload["tenant_id"])

    status = await ctx.batch_adapter.get_status(batch_id)

    sm = get_sessionmaker(ctx.settings.database_url)
    async with sm() as session:
        sub_repo = BatchSubmissionRepo(session)
        submission = await sub_repo.get_by_batch_id(batch_id)
        if submission is None:
            return  # canceled or already reaped
        await sub_repo.mark_polled(submission.id)
        await session.commit()

    if status is BatchStatus.IN_PROGRESS:
        delay = _next_poll_delay(envelope.attempts)
        await ctx.queue.enqueue(
            TaskKind.BATCH_POLL,
            {"batch_id": batch_id, "tenant_id": str(tenant_id)},
            tenant_id=tenant_id,
            delay_seconds=delay,
        )
        return

    # Terminal status — pull results, fan out to jobs.
    from ocr_to_report.adapters.vision import BatchHandle  # noqa: PLC0415

    job_id_strs = list(submission.job_ids.get("ids", []))
    handle = BatchHandle(
        batch_id=batch_id,
        custom_ids=job_id_strs,
        submitted_at=submission.submitted_at,
    )

    if status in {BatchStatus.CANCELED, BatchStatus.EXPIRED, BatchStatus.ERRORED}:
        # Mark every job failed without trying to fetch.
        async with sm() as session:
            jobs_repo = JobRepo(session)
            for jid in job_id_strs:
                await jobs_repo.mark_failed(
                    uuid.UUID(jid),
                    error_detail=f"batch terminal status: {status.value}",
                )
            sub_repo = BatchSubmissionRepo(session)
            await sub_repo.mark_completed(submission.id, status=status.value)
            await session.commit()
        return

    results = await ctx.batch_adapter.fetch_results(handle)

    async with sm() as session:
        jobs_repo = JobRepo(session)
        usage_repo = UsageRepo(session)
        period_start, period_end = _current_month_period()
        for jid, item in results.items():
            job_uuid = uuid.UUID(jid)
            if not item.is_success or item.extraction is None:
                await jobs_repo.mark_failed(
                    job_uuid,
                    error_detail=item.error_detail or "unknown batch failure",
                )
                continue
            ext = item.extraction
            await jobs_repo.mark_succeeded(
                job_uuid,
                output_blob_key="",  # batch jobs don't render synchronously
                provider_used=ext.provider.value,
                model_id_used=ext.model_id,
                tokens_input=ext.usage.input_tokens,
                tokens_output=ext.usage.output_tokens,
                usd_cost=ext.usage.usd_cost,
            )
            # v0.3.0: batch jobs ship platform-billed only. BYOK on
            # the batch path is YAGNI-deferred to v0.7.0; the explicit
            # tag makes the intent visible at the call site.
            await usage_repo.increment(
                tenant_id=tenant_id,
                period_start=period_start,
                period_end=period_end,
                transcripts=1,
                tokens_input=ext.usage.input_tokens,
                tokens_output=ext.usage.output_tokens,
                cache_read_tokens=ext.usage.cache_read_input_tokens,
                cache_creation_tokens=ext.usage.cache_creation_input_tokens,
                usd_cost=ext.usage.usd_cost,
                billing_path="platform",
            )
        sub_repo = BatchSubmissionRepo(session)
        await sub_repo.mark_completed(submission.id, status=status.value)
        await session.commit()


# ─── RETENTION_SWEEP ─────────────────────────────────────────
async def handle_retention_sweep(ctx: WorkerContext, envelope: TaskEnvelope) -> None:
    """Run one retention sweep across all tenants.

    Payload: ``{"limit": int}`` (optional; defaults to 100).
    """
    from ocr_to_report.worker.retention import RetentionService  # noqa: PLC0415

    limit = int(envelope.payload.get("limit", 100))
    sm = get_sessionmaker(ctx.settings.database_url)
    service = RetentionService(
        sessionmaker=sm,
        blob_store=ctx.blob_store,
        encryptor=ctx.encryptor,
    )
    await service.sweep(limit=limit)


# ─── TRANSCRIPT_JOB (placeholder) ────────────────────────────
async def handle_transcript_job(ctx: WorkerContext, envelope: TaskEnvelope) -> None:
    """Placeholder for the async sync-style processor.

    Phase 7 ships the queue + batch lane; the async TRANSCRIPT_JOB lane
    arrives in Phase 8 along with SLA tiers (the SLA tier decides
    whether a request is processed sync or async). For now, the handler
    marks the job failed with a clear "not implemented" reason so any
    accidentally-enqueued tasks are visible.
    """
    job_id = uuid.UUID(envelope.payload["job_id"])
    sm = get_sessionmaker(ctx.settings.database_url)
    async with sm() as session:
        jobs_repo = JobRepo(session)
        await jobs_repo.mark_failed(
            job_id,
            error_detail="async TRANSCRIPT_JOB lane scheduled for Phase 8",
        )
        await session.commit()


# ─── Helpers ─────────────────────────────────────────────────
async def _build_vision_request(ctx: WorkerContext, job: Job) -> VisionRequest:
    """Reconstruct a vision request for an enqueued batch job."""
    if job.input_blob_key is None:
        raise ValueError(f"job {job.id} has no input_blob_key")
    if job.profile_id is None:
        raise ValueError(f"job {job.id} has no profile_id")
    blob = await ctx.blob_store.get(job.input_blob_key)
    bundle = ctx.profile_registry.get(job.profile_id)

    from ocr_to_report.adapters.vision import preprocess  # noqa: PLC0415

    images = preprocess(blob)
    return VisionRequest(
        images=images,
        prompt=bundle.extraction_prompt_template,
        output_schema=compile_schema(bundle.extraction_schema),
        schema_version=bundle.manifest.version,
        profile_id=job.profile_id,
    )


async def _resolve_tenant(ctx: WorkerContext, tenant_id: uuid.UUID) -> Any:
    """Load a tenant row + DEK; raises if archived or missing."""
    sm = get_sessionmaker(ctx.settings.database_url)
    async with sm() as session:
        tenants_repo = TenantRepo(session, ctx.encryptor)
        tenant = await tenants_repo.get(tenant_id)
        if tenant is None:
            raise ValueError(f"tenant {tenant_id} not found")
        dek = await tenants_repo.unwrap_dek(tenant)
        await session.commit()
    return tenant, dek


def _next_poll_delay(attempts: int) -> float:
    """Exponential backoff for batch polling, capped at 30 minutes."""
    base = 60.0  # 1 min
    return float(min(base * (2**attempts), 30.0 * 60.0))


def _current_month_period() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


# Suppress unused-imports referenced only as type hints.
_ = (timedelta,)


__all__ = [
    "handle_batch_poll",
    "handle_batch_submit",
    "handle_retention_sweep",
    "handle_transcript_job",
]

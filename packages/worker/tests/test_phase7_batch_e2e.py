"""Phase 7 — end-to-end batch flow.

Exercises the full BATCH_SUBMIT → BATCH_POLL → fan-out flow against a
fake batch adapter, real SQLite database, and real LocalBlobStore.

The test:
1. Inserts a tenant + 3 pending batch-kind jobs with input blobs.
2. Enqueues a BATCH_SUBMIT envelope.
3. Spins the worker; the handler submits a batch.
4. Spins the worker again; the BATCH_POLL handler sees ENDED, fetches
   results, marks 2 jobs succeeded + 1 failed, and updates usage.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from PIL import Image as PILImage

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.db import get_sessionmaker
from ocr_to_report.adapters.db.repositories import (
    BatchSubmissionRepo,
    JobRepo,
    TenantRepo,
    UsageRepo,
)
from ocr_to_report.adapters.queue import InMemoryQueue, TaskKind
from ocr_to_report.adapters.vision import (
    BatchHandle,
    BatchItemResult,
    BatchStatus,
    ExtractionResult,
    InMemoryAsyncCache,
    TokenUsage,
    VisionProvider,
)
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.targets import TargetRegistry
from ocr_to_report.worker.context import WorkerContext
from ocr_to_report.worker.runner import WorkerRunner

REPO_ROOT = Path(__file__).resolve().parents[3]


def _png_bytes() -> bytes:
    img = PILImage.new("RGB", (400, 600), color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _success_extraction(name: str = "Jan Kowalski") -> ExtractionResult:
    return ExtractionResult(
        raw_extraction={
            "full_name": name,
            "birth_date": "2010-01-15",
            "school_year": "2023/2024",
            "current_class_name": "pierwszej",
            "school_name": "Test Academy LO",
            "city": "Warszawa",
            "region": "mazowieckie",
            "promoted": True,
            "promoted_with_distinction": False,
            "conduct": "wzorowe",
            "subjects": [
                {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
            ],
            "advanced_subjects": [],
        },
        confidence=0.93,
        field_confidences=None,
        warnings=[],
        provider=VisionProvider.ANTHROPIC,
        model_id="claude-haiku-4-5",
        usage=TokenUsage(input_tokens=1500, output_tokens=300, usd_cost=0.0015),
    )


@dataclass
class _FakeBatchAdapter:
    """Test double for AnthropicBatchAdapter that records submissions."""

    submitted_batches: list[BatchHandle]
    next_status: BatchStatus
    next_results: dict[str, BatchItemResult]
    submit_mock: AsyncMock
    get_status_mock: AsyncMock
    fetch_results_mock: AsyncMock

    @classmethod
    def make(cls, *, status: BatchStatus, results: dict[str, BatchItemResult]) -> _FakeBatchAdapter:
        async def _submit(requests: list[tuple[str, Any]]) -> BatchHandle:
            handle = BatchHandle(
                batch_id=f"batch_{uuid.uuid4().hex[:8]}",
                custom_ids=[cid for cid, _ in requests],
                submitted_at=datetime.now(tz=UTC),
            )
            inst.submitted_batches.append(handle)
            return handle

        async def _get_status(_batch_id: str) -> BatchStatus:
            return inst.next_status

        async def _fetch_results(handle: BatchHandle) -> dict[str, BatchItemResult]:
            results: dict[str, BatchItemResult] = {}
            for cid in handle.custom_ids:
                results[cid] = inst.next_results.get(
                    cid,
                    BatchItemResult(custom_id=cid, extraction=None, error_detail="missing"),
                )
            return results

        inst = cls(
            submitted_batches=[],
            next_status=status,
            next_results=results,
            submit_mock=AsyncMock(side_effect=_submit),
            get_status_mock=AsyncMock(side_effect=_get_status),
            fetch_results_mock=AsyncMock(side_effect=_fetch_results),
        )
        return inst

    async def submit(self, requests: list[tuple[str, Any]]) -> BatchHandle:
        result: BatchHandle = await self.submit_mock(requests)
        return result

    async def get_status(self, batch_id: str) -> BatchStatus:
        result: BatchStatus = await self.get_status_mock(batch_id)
        return result

    async def fetch_results(self, handle: BatchHandle) -> dict[str, BatchItemResult]:
        result: dict[str, BatchItemResult] = await self.fetch_results_mock(handle)
        return result

    async def aclose(self) -> None:
        return None


@pytest.fixture
async def setup_db(settings: Settings, db_setup: None) -> AsyncIterator[None]:
    yield


@pytest.fixture
async def seeded_tenant_with_batch_jobs(
    settings: Settings,
    setup_db: None,
    png_bytes: bytes,
) -> dict[str, Any]:
    """Insert a tenant + 3 pending batch-kind jobs with input blobs."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    blob_store = LocalBlobStore(settings.blob_local_root)

    async with sm() as session:
        tenants_repo = TenantRepo(session, encryptor)
        tenant, _dek = await tenants_repo.create(name="Acme", slug="acme")
        jobs_repo = JobRepo(session)
        job_ids: list[uuid.UUID] = []
        for _ in range(3):
            job = await jobs_repo.create(
                tenant_id=tenant.id,
                kind="batch",
                profile_id="pl.lo.swiadectwo_szkolne.v1",
                target_id="us-hs.v1",
                pipeline_id="batch_economy_v1",
            )
            job_ids.append(job.id)
            in_key = f"jobs/{job.id}/input"
            await blob_store.put(in_key, png_bytes)
            job.input_blob_key = in_key
        await session.commit()

    return {"tenant_id": tenant.id, "job_ids": job_ids}


def _build_ctx(
    settings: Settings,
    *,
    queue: InMemoryQueue,
    batch_adapter: Any,
) -> WorkerContext:
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    blob_store = LocalBlobStore(settings.blob_local_root)
    bundle_roots = {t.id: (settings.targets_root / t.id).resolve() for t in target_registry.all()}
    return WorkerContext(
        settings=settings,
        queue=queue,
        encryptor=encryptor,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=blob_store,
        vision_router=MagicMock(),
        batch_adapter=batch_adapter,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
    )


@pytest.mark.asyncio
async def test_batch_submit_handler_persists_submission_and_marks_jobs_running(
    settings: Settings,
    seeded_tenant_with_batch_jobs: dict[str, Any],
) -> None:
    fixture = seeded_tenant_with_batch_jobs
    adapter = _FakeBatchAdapter.make(status=BatchStatus.IN_PROGRESS, results={})
    queue = InMemoryQueue()
    ctx = _build_ctx(settings, queue=queue, batch_adapter=adapter)

    runner = WorkerRunner(ctx=ctx)
    await queue.enqueue(
        TaskKind.BATCH_SUBMIT,
        {"tenant_id": str(fixture["tenant_id"])},
        tenant_id=fixture["tenant_id"],
    )

    dispatched = await runner.run_once(timeout_seconds=2.0)
    assert dispatched is True

    # Adapter received 3 vision requests with the 3 job ids as custom_ids.
    adapter.submit_mock.assert_awaited_once()
    await_args = adapter.submit_mock.await_args
    assert await_args is not None
    submitted = await_args.args[0]
    assert {cid for cid, _ in submitted} == {str(j) for j in fixture["job_ids"]}

    # BatchSubmission persisted; jobs are now 'running'.
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        sub_repo = BatchSubmissionRepo(session)
        in_progress = await sub_repo.list_in_progress()
        assert len(in_progress) == 1
        assert in_progress[0].status == "in_progress"
        assert sorted(in_progress[0].job_ids["ids"]) == sorted(str(j) for j in fixture["job_ids"])

        jobs_repo = JobRepo(session)
        for jid in fixture["job_ids"]:
            job = await jobs_repo.get(jid)
            assert job is not None
            assert job.status == "running"

    # A BATCH_POLL envelope was scheduled (delayed; not visible yet).
    # Pop it after a short delay-friendly lease — we just verify the
    # in-flight count plus pending count are 0 (it's in delayed list).
    assert queue.in_flight_count() == 0


@pytest.mark.asyncio
async def test_batch_poll_marks_results_and_completes_submission(
    settings: Settings,
    seeded_tenant_with_batch_jobs: dict[str, Any],
) -> None:
    fixture = seeded_tenant_with_batch_jobs
    job_ids = fixture["job_ids"]

    # First-pass: submit the batch with the IN_PROGRESS-returning adapter
    # so we get a real BatchSubmission row.
    submit_adapter = _FakeBatchAdapter.make(status=BatchStatus.IN_PROGRESS, results={})
    queue = InMemoryQueue()
    ctx = _build_ctx(settings, queue=queue, batch_adapter=submit_adapter)
    runner = WorkerRunner(ctx=ctx)

    await queue.enqueue(
        TaskKind.BATCH_SUBMIT,
        {"tenant_id": str(fixture["tenant_id"])},
        tenant_id=fixture["tenant_id"],
    )
    await runner.run_once(timeout_seconds=2.0)
    batch_id = submit_adapter.submitted_batches[0].batch_id

    # Now build a *second* adapter that says ENDED + has results for
    # 2 jobs (success) + 1 (failure), and a fresh queue.
    poll_results: dict[str, BatchItemResult] = {
        str(job_ids[0]): BatchItemResult(
            custom_id=str(job_ids[0]),
            extraction=_success_extraction("Anna Nowak"),
            error_detail=None,
        ),
        str(job_ids[1]): BatchItemResult(
            custom_id=str(job_ids[1]),
            extraction=_success_extraction("Piotr Wiśniewski"),
            error_detail=None,
        ),
        str(job_ids[2]): BatchItemResult(
            custom_id=str(job_ids[2]),
            extraction=None,
            error_detail="image too dark",
        ),
    }
    poll_adapter = _FakeBatchAdapter.make(status=BatchStatus.ENDED, results=poll_results)
    queue2 = InMemoryQueue()
    ctx2 = _build_ctx(settings, queue=queue2, batch_adapter=poll_adapter)
    runner2 = WorkerRunner(ctx=ctx2)
    await queue2.enqueue(
        TaskKind.BATCH_POLL,
        {"batch_id": batch_id, "tenant_id": str(fixture["tenant_id"])},
        tenant_id=fixture["tenant_id"],
    )
    await runner2.run_once(timeout_seconds=2.0)

    # 2 jobs succeeded, 1 failed; submission marked ended.
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        jobs_repo = JobRepo(session)
        statuses = []
        for jid in job_ids:
            job = await jobs_repo.get(jid)
            assert job is not None
            statuses.append(job.status)
        assert sorted(statuses) == ["failed", "succeeded", "succeeded"]

        # Failed job carries the error detail.
        failed = await jobs_repo.get(job_ids[2])
        assert failed is not None
        assert failed.error_detail is not None
        assert "image too dark" in failed.error_detail

        # Submission row reflects ENDED.
        sub_repo = BatchSubmissionRepo(session)
        sub = await sub_repo.get_by_batch_id(batch_id)
        assert sub is not None
        assert sub.status == "ended"
        assert sub.completed_at is not None

        # Usage rolls up the 2 successful items' tokens.
        usage_repo = UsageRepo(session)
        period_start = datetime.now(tz=UTC).replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        if period_start.month == 12:
            period_end = period_start.replace(year=period_start.year + 1, month=1)
        else:
            period_end = period_start.replace(month=period_start.month + 1)
        usage = await usage_repo.get_period(
            tenant_id=fixture["tenant_id"],
            period_start=period_start,
            period_end=period_end,
        )
        assert usage is not None
        assert usage.transcripts_processed == 2
        assert usage.tokens_input == 3000  # 1500 + 1500
        assert usage.tokens_output == 600  # 300 + 300


@pytest.mark.asyncio
async def test_batch_poll_reschedules_when_in_progress(
    settings: Settings,
    seeded_tenant_with_batch_jobs: dict[str, Any],
) -> None:
    """Polling an in-progress batch enqueues another BATCH_POLL with delay."""
    fixture = seeded_tenant_with_batch_jobs
    submit_adapter = _FakeBatchAdapter.make(status=BatchStatus.IN_PROGRESS, results={})
    queue = InMemoryQueue()
    ctx = _build_ctx(settings, queue=queue, batch_adapter=submit_adapter)
    runner = WorkerRunner(ctx=ctx)

    await queue.enqueue(
        TaskKind.BATCH_SUBMIT,
        {"tenant_id": str(fixture["tenant_id"])},
        tenant_id=fixture["tenant_id"],
    )
    await runner.run_once(timeout_seconds=2.0)
    batch_id = submit_adapter.submitted_batches[0].batch_id

    # Now poll the IN_PROGRESS batch — handler should call get_status,
    # then re-enqueue a delayed BATCH_POLL.
    poll_adapter = _FakeBatchAdapter.make(status=BatchStatus.IN_PROGRESS, results={})
    queue2 = InMemoryQueue()
    ctx2 = _build_ctx(settings, queue=queue2, batch_adapter=poll_adapter)
    runner2 = WorkerRunner(ctx=ctx2)
    await queue2.enqueue(
        TaskKind.BATCH_POLL,
        {"batch_id": batch_id, "tenant_id": str(fixture["tenant_id"])},
        tenant_id=fixture["tenant_id"],
    )
    await runner2.run_once(timeout_seconds=2.0)

    # The handler should have called get_status but NOT fetch_results.
    poll_adapter.get_status_mock.assert_awaited_once_with(batch_id)
    poll_adapter.fetch_results_mock.assert_not_awaited()

    # Jobs are still 'running' (not yet completed).
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        jobs_repo = JobRepo(session)
        for jid in fixture["job_ids"]:
            job = await jobs_repo.get(jid)
            assert job is not None
            assert job.status == "running"

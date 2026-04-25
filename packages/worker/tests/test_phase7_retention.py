"""Phase 7 — RetentionService end-to-end against SQLite + LocalBlobStore."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.db import get_sessionmaker
from ocr_to_report.adapters.db.repositories import (
    JobRepo,
    TenantRepo,
    TranscriptRepo,
)
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.canonical import (
    CanonicalGrade,
    CanonicalStudent,
    CanonicalSubject,
    CanonicalTranscript,
)
from ocr_to_report.core.enums.canonical import CanonicalSubjectId
from ocr_to_report.worker.retention import RetentionService


def _build_canonical() -> CanonicalTranscript:
    return CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=CanonicalStudent(
            full_name="Test Student",
            birth_date=date(2009, 1, 1),
            school_year="2023/2024",
            source_year_index=1,
            target_year_index=2,
            promoted=True,
            school_name="Test Academy",
            city="Warsaw",
            region="mazowieckie",
            confidence=1.0,
        ),
        subjects=[
            CanonicalSubject(
                canonical_id=CanonicalSubjectId.MATHEMATICS,
                raw_source_name="Matematyka",
                grade=CanonicalGrade.from_normalized(
                    4 / 6,
                    raw_source_value="bardzo dobry",
                    raw_source_scale_id="pl.6point.v1",
                    confidence=0.95,
                ),
                base_hours=108,
                confidence=0.95,
            ),
        ],
        overall_confidence=0.92,
    )


@pytest.fixture
async def seeded_expired_job(
    settings: Settings,
    db_setup: None,
) -> dict[str, Any]:
    """Insert a tenant + an expired job + transcript + blobs."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    blob_store = LocalBlobStore(settings.blob_local_root)

    async with sm() as session:
        tenants_repo = TenantRepo(session, encryptor)
        tenant, dek = await tenants_repo.create(name="Acme", slug="acme")
        jobs_repo = JobRepo(session)
        job = await jobs_repo.create(
            tenant_id=tenant.id,
            kind="sync",
            profile_id="pl.lo.swiadectwo_szkolne.v1",
            target_id="us-hs.v1",
            input_blob_key=f"jobs/{uuid.uuid4()}/input",
            expires_at=datetime.now(tz=UTC) - timedelta(days=1),
        )
        # Set output blob key + persist input/output blobs.
        out_key = f"jobs/{job.id}/output.xlsx"
        in_key = job.input_blob_key
        assert in_key is not None
        await blob_store.put(in_key, b"input-bytes")
        await blob_store.put(out_key, b"output-bytes")
        await jobs_repo.mark_succeeded(
            job.id,
            output_blob_key=out_key,
            provider_used="anthropic",
            model_id_used="claude-haiku-4-5",
            tokens_input=1000,
            tokens_output=200,
            usd_cost=0.002,
        )

        transcripts_repo = TranscriptRepo(session, encryptor)
        await transcripts_repo.store(
            tenant_id=tenant.id,
            job_id=job.id,
            transcript=_build_canonical(),
            dek=dek,
            input_sha256="a" * 64,
            output_sha256="b" * 64,
        )
        await session.commit()

    return {
        "tenant_id": tenant.id,
        "job_id": job.id,
        "input_blob_key": in_key,
        "output_blob_key": out_key,
        "encryptor": encryptor,
        "blob_store": blob_store,
        "sessionmaker": sm,
    }


@pytest.mark.asyncio
async def test_retention_purges_expired_job_artifacts(
    seeded_expired_job: dict[str, Any],
    settings: Settings,
) -> None:
    fixture = seeded_expired_job

    service = RetentionService(
        sessionmaker=fixture["sessionmaker"],
        blob_store=fixture["blob_store"],
        encryptor=fixture["encryptor"],
    )
    report = await service.sweep(limit=10)

    assert report.jobs_inspected == 1
    assert report.jobs_purged == 1
    assert report.blobs_deleted == 2
    assert report.errors == []

    # Verify job + transcript rows are gone, and blobs no longer exist.
    sm = fixture["sessionmaker"]
    async with sm() as session:
        jobs_repo = JobRepo(session)
        assert await jobs_repo.get(fixture["job_id"]) is None
        transcripts_repo = TranscriptRepo(session, fixture["encryptor"])
        assert (
            await transcripts_repo.fetch(
                tenant_id=fixture["tenant_id"],
                job_id=fixture["job_id"],
                dek=b"x" * 32,  # not actually decrypted since row is gone
            )
            is None
        )

    blob_root = Path(settings.blob_local_root)
    in_blob = blob_root / fixture["input_blob_key"]
    out_blob = blob_root / fixture["output_blob_key"]
    assert not in_blob.exists()
    assert not out_blob.exists()


@pytest.mark.asyncio
async def test_retention_skips_unexpired_jobs(
    settings: Settings,
    db_setup: None,
) -> None:
    """Jobs with no expires_at or expires_at in the future are untouched."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    blob_store = LocalBlobStore(settings.blob_local_root)

    async with sm() as session:
        tenants_repo = TenantRepo(session, encryptor)
        tenant, _ = await tenants_repo.create(name="Acme", slug="acme")
        jobs_repo = JobRepo(session)
        await jobs_repo.create(
            tenant_id=tenant.id,
            kind="sync",
            expires_at=datetime.now(tz=UTC) + timedelta(days=30),
        )
        await jobs_repo.create(tenant_id=tenant.id, kind="sync")  # no expires_at
        await session.commit()

    service = RetentionService(
        sessionmaker=sm,
        blob_store=blob_store,
        encryptor=encryptor,
    )
    report = await service.sweep()
    assert report.jobs_inspected == 0
    assert report.jobs_purged == 0


@pytest.mark.asyncio
async def test_retention_writes_audit_log_entry(
    seeded_expired_job: dict[str, Any],
) -> None:
    """Each purge appends a 'job.retention_purged' audit-log entry."""
    fixture = seeded_expired_job
    service = RetentionService(
        sessionmaker=fixture["sessionmaker"],
        blob_store=fixture["blob_store"],
        encryptor=fixture["encryptor"],
    )
    await service.sweep(limit=10)

    from ocr_to_report.adapters.db.models import AuditLog  # noqa: PLC0415

    sm = fixture["sessionmaker"]
    async with sm() as session:
        from sqlalchemy import select  # noqa: PLC0415

        result = await session.execute(
            select(AuditLog).where(AuditLog.action == "job.retention_purged")
        )
        rows = list(result.scalars().all())
        assert len(rows) == 1
        assert rows[0].resource_id == str(fixture["job_id"])
        assert rows[0].actor_type == "system"

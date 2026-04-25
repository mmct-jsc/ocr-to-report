"""End-to-end persistence tests against an in-memory SQLite database.

Validates the repository layer wired together: tenant creation +
DEK envelope encryption, API key issue/auth, job lifecycle, transcript
encryption round-trip, audit chain build + verify, usage rollup,
idempotency cache, webhook secret encryption.

Postgres-specific behavior (RLS) is exercised by phase 5g integration
tests gated on ``RUN_DB_TESTS=1`` (Phase 5f); SQLite is sufficient to
prove the SQL is dialect-agnostic and the repos work as designed.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base
from ocr_to_report.adapters.db.repositories import (
    ApiKeyRepo,
    AuditRepo,
    IdempotencyRepo,
    JobRepo,
    TenantRepo,
    TranscriptRepo,
    UsageRepo,
    WebhookRepo,
)


@pytest.fixture
def kek_env(monkeypatch: pytest.MonkeyPatch) -> str:
    kek = base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode()
    monkeypatch.setenv("OCR2R_KEK_B64", kek)
    return kek


@pytest.fixture
def encryptor(kek_env: str) -> EnvelopeEncryptor:
    return EnvelopeEncryptor(EnvKEKProvider())


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test in-memory SQLite database with a fresh schema."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        try:
            yield s
            await s.commit()
        finally:
            await s.close()
    await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_create_and_dek_round_trip(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    repo = TenantRepo(session, encryptor)
    tenant, dek_plain = await repo.create(name="Acme", slug="acme")
    assert tenant.id is not None
    assert tenant.dek_wrapped != dek_plain
    # Round-trip: unwrap from DB row gives the same plaintext DEK
    fetched = await repo.get(tenant.id)
    assert fetched is not None
    assert await repo.unwrap_dek(fetched) == dek_plain


@pytest.mark.asyncio
async def test_tenant_get_by_slug(session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
    repo = TenantRepo(session, encryptor)
    await repo.create(name="Acme", slug="acme")
    found = await repo.get_by_slug("acme")
    assert found is not None
    assert found.slug == "acme"


@pytest.mark.asyncio
async def test_crypto_shred_destroys_dek(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    repo = TenantRepo(session, encryptor)
    tenant, _ = await repo.create(name="Acme", slug="acme")
    original_wrapped = tenant.dek_wrapped
    await repo.crypto_shred(tenant.id)
    fetched = await repo.get(tenant.id)
    assert fetched is not None
    assert fetched.dek_wrapped != original_wrapped
    # The wrapped DEK is now random bytes; unwrap must fail.
    from ocr_to_report.adapters.crypto.envelope import CryptoError  # noqa: PLC0415

    with pytest.raises(CryptoError):
        await repo.unwrap_dek(fetched)
    assert fetched.archived_at is not None


@pytest.mark.asyncio
async def test_api_key_issue_authenticate_revoke(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    keys = ApiKeyRepo(session)
    tenant, _dek = await tenants.create(name="Acme", slug="acme")

    row, plain = await keys.issue(
        tenant_id=tenant.id,
        scopes=["transcripts:write"],
        label="ci",
    )
    assert plain.startswith("sk_test_")
    assert row.prefix == "sk_test_"

    auth = await keys.authenticate(plain)
    assert auth is not None
    assert auth.id == row.id

    # Revoke: subsequent auth fails
    await keys.revoke(row.id)
    assert await keys.authenticate(plain) is None


@pytest.mark.asyncio
async def test_job_lifecycle(session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
    tenants = TenantRepo(session, encryptor)
    jobs = JobRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    job = await jobs.create(
        tenant_id=tenant.id,
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        idempotency_key="idem-1",
    )
    assert job.status == "pending"

    await jobs.mark_running(job.id)
    refreshed = await jobs.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "running"

    await jobs.mark_succeeded(
        job.id,
        output_blob_key="out/job-1.xlsx",
        provider_used="anthropic",
        model_id_used="claude-haiku-4-5",
        tokens_input=1000,
        tokens_output=200,
        usd_cost=0.002,
    )
    refreshed = await jobs.get(job.id)
    assert refreshed is not None
    assert refreshed.status == "succeeded"
    assert refreshed.output_blob_key == "out/job-1.xlsx"
    assert refreshed.completed_at is not None


@pytest.mark.asyncio
async def test_job_idempotency_lookup(session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
    tenants = TenantRepo(session, encryptor)
    jobs = JobRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    job = await jobs.create(tenant_id=tenant.id, idempotency_key="idem-42")
    found = await jobs.get_by_idempotency(tenant.id, "idem-42")
    assert found is not None
    assert found.id == job.id


@pytest.mark.asyncio
async def test_audit_chain_append_and_verify(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    audit = AuditRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    for action in ["job.create", "job.start", "job.complete"]:
        await audit.append(
            tenant_id=tenant.id,
            actor_type="api_key",
            actor_id_hash="a" * 64,
            action=action,
            resource_type="job",
            resource_id="job-1",
        )
    await session.flush()

    # Verifier walks the whole chain in order
    count = await audit.verify_for_tenant(tenant.id)
    assert count == 3


@pytest.mark.asyncio
async def test_audit_chain_links_via_prev_hash(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    audit = AuditRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    e1 = await audit.append(
        tenant_id=tenant.id,
        actor_type="system",
        actor_id_hash="0" * 64,
        action="bootstrap",
        resource_type="tenant",
    )
    e2 = await audit.append(
        tenant_id=tenant.id,
        actor_type="system",
        actor_id_hash="0" * 64,
        action="seed",
        resource_type="tenant",
    )
    assert e2.prev_hash == e1.row_hash


@pytest.mark.asyncio
async def test_transcript_encrypt_decrypt(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    from ocr_to_report.core.canonical import (  # noqa: PLC0415
        CanonicalGrade,
        CanonicalStudent,
        CanonicalSubject,
        CanonicalTranscript,
    )
    from ocr_to_report.core.enums.canonical import CanonicalSubjectId  # noqa: PLC0415

    tenants = TenantRepo(session, encryptor)
    jobs = JobRepo(session)
    transcripts = TranscriptRepo(session, encryptor)

    tenant, dek = await tenants.create(name="Acme", slug="acme")
    job = await jobs.create(tenant_id=tenant.id)

    student = CanonicalStudent(
        full_name="Jan Kowalski",
        birth_date=None,
        school_year="2023/2024",
        source_year_index=1,
        target_year_index=2,
        promoted=True,
        school_name="Test LO",
    )
    subject = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=CanonicalGrade.from_normalized(
            5 / 6, raw_source_value="celujący", raw_source_scale_id="pl.6point.v1"
        ),
        base_hours=108,
    )
    transcript = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=student,
        subjects=[subject],
        overall_confidence=0.95,
    )

    row = await transcripts.store(
        tenant_id=tenant.id,
        job_id=job.id,
        transcript=transcript,
        dek=dek,
        input_sha256="a" * 64,
    )
    assert row.canonical_encrypted != b""
    assert row.overall_confidence == pytest.approx(0.95)

    fetched = await transcripts.fetch(tenant_id=tenant.id, job_id=job.id, dek=dek)
    assert fetched is not None
    student_obj = fetched["student"]
    assert isinstance(student_obj, dict)
    assert student_obj["full_name"] == "Jan Kowalski"


@pytest.mark.asyncio
async def test_usage_rollup_increments(session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
    tenants = TenantRepo(session, encryptor)
    usage = UsageRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")
    period_start = datetime(2026, 1, 1, tzinfo=UTC)
    period_end = datetime(2026, 2, 1, tzinfo=UTC)

    await usage.increment(
        tenant_id=tenant.id,
        period_start=period_start,
        period_end=period_end,
        transcripts=1,
        tokens_input=1000,
        tokens_output=200,
        usd_cost=0.002,
    )
    await usage.increment(
        tenant_id=tenant.id,
        period_start=period_start,
        period_end=period_end,
        transcripts=2,
        tokens_input=500,
        tokens_output=100,
        usd_cost=0.001,
    )
    row = await usage.get_period(
        tenant_id=tenant.id, period_start=period_start, period_end=period_end
    )
    assert row is not None
    assert row.transcripts_processed == 3
    assert row.tokens_input == 1500
    assert row.tokens_output == 300
    assert float(row.usd_cost) == pytest.approx(0.003, rel=1e-3)


@pytest.mark.asyncio
async def test_idempotency_replay(session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
    tenants = TenantRepo(session, encryptor)
    idem = IdempotencyRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    expires = datetime.now(tz=UTC) + timedelta(hours=24)
    await idem.store(
        tenant_id=tenant.id,
        key="req-1",
        request_hash="h" * 64,
        response_status=200,
        response_body=b'{"ok":true}',
        response_content_type="application/json",
        expires_at=expires,
    )
    row = await idem.get(tenant_id=tenant.id, key="req-1", request_hash="h" * 64)
    assert row is not None
    assert row.response_status == 200

    # Different hash returns None (cache miss / replay-mismatch)
    row2 = await idem.get(tenant_id=tenant.id, key="req-1", request_hash="x" * 64)
    assert row2 is None


@pytest.mark.asyncio
async def test_idempotency_purge_expired(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    idem = IdempotencyRepo(session)
    tenant, _ = await tenants.create(name="Acme", slug="acme")

    past = datetime.now(tz=UTC) - timedelta(hours=1)
    await idem.store(
        tenant_id=tenant.id,
        key="old",
        request_hash="h",
        response_status=200,
        response_body=b"",
        response_content_type="application/json",
        expires_at=past,
    )
    purged = await idem.purge_expired()
    assert purged == 1


@pytest.mark.asyncio
async def test_webhook_secret_encryption(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    webhooks = WebhookRepo(session, encryptor)
    tenant, dek = await tenants.create(name="Acme", slug="acme")

    secret_plain = b"whsec_" + secrets.token_bytes(24)
    row = await webhooks.create(
        tenant_id=tenant.id,
        url="https://acme.example.com/hook",
        events=["job.completed", "job.failed"],
        secret_plain=secret_plain,
        dek=dek,
    )
    assert row.secret_encrypted != secret_plain

    decrypted = await webhooks.secret(row, dek)
    assert decrypted == secret_plain


@pytest.mark.asyncio
async def test_webhook_list_active_filtered_by_event(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> None:
    tenants = TenantRepo(session, encryptor)
    webhooks = WebhookRepo(session, encryptor)
    tenant, dek = await tenants.create(name="Acme", slug="acme")

    await webhooks.create(
        tenant_id=tenant.id,
        url="https://a",
        events=["job.completed"],
        secret_plain=b"x",
        dek=dek,
    )
    await webhooks.create(
        tenant_id=tenant.id,
        url="https://b",
        events=["job.failed"],
        secret_plain=b"y",
        dek=dek,
    )
    completed = await webhooks.list_active(tenant.id, event="job.completed")
    assert len(completed) == 1
    assert completed[0].url == "https://a"

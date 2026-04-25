"""Phase 9 — Python SDK end-to-end against the FastAPI app.

Uses ``httpx.WSGITransport`` ... no, FastAPI is ASGI: drives the SDK
against an in-process ``ASGITransport`` + the real ``create_app``,
exercising the full HTTP path (auth, problem-detail, file upload).
This is the canonical test for "the SDK matches the server".
"""

from __future__ import annotations

import base64
import io
import secrets
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from PIL import Image as PILImage

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
from ocr_to_report.adapters.queue import InMemoryQueue
from ocr_to_report.adapters.vision import (
    ExtractionResult,
    FixedPolicy,
    InMemoryAsyncCache,
    ProviderRouter,
    TokenUsage,
    VisionProvider,
)
from ocr_to_report.api.app import create_app
from ocr_to_report.api.deps import AppState
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import SLA_PRESETS
from ocr_to_report.core.targets import TargetRegistry
from ocr_to_report.sdk_py import (
    AsyncClient,
    AuthenticationError,
    Client,
    ForbiddenError,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


def _png() -> bytes:
    img = PILImage.new("RGB", (400, 600), color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _polish_extraction() -> dict[str, Any]:
    return {
        "full_name": "Jan Kowalski",
        "birth_date": "2010-01-15",
        "school_year": "2023/2024",
        "current_class_name": "pierwszej",
        "school_name": "Test Academy LO",
        "city": "Warszawa",
        "region": "mazowieckie",
        "promoted": True,
        "promoted_with_distinction": True,
        "conduct": "wzorowe",
        "subjects": [
            {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
        ],
        "advanced_subjects": [],
    }


class _StubAdapter:
    name = VisionProvider.MOCK

    def __init__(self) -> None:
        self.extract = AsyncMock(
            return_value=ExtractionResult(
                raw_extraction=_polish_extraction(),
                confidence=0.95,
                field_confidences=None,
                warnings=[],
                provider=VisionProvider.MOCK,
                model_id="mock",
                usage=TokenUsage(input_tokens=1500, output_tokens=300, usd_cost=0.003),
            )
        )

    async def aclose(self) -> None:
        return None


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(
        "OCR2R_KEK_B64",
        base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
    )
    return Settings(
        env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        blob_backend="local",
        blob_local_root=tmp_path / "blob",
        kek_b64=base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
        profiles_root=REPO_ROOT / "profiles",
        targets_root=REPO_ROOT / "targets",
    )


@pytest.fixture
async def db_setup(settings: Settings) -> None:
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def seeded(settings: Settings, db_setup: None) -> dict[str, Any]:
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name="Acme", slug="acme")
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key}


def _build_app_state(settings: Settings) -> AppState:
    """Construct an AppState wired to the stub vision adapter."""
    router = ProviderRouter(
        {VisionProvider.MOCK: _StubAdapter()},
        FixedPolicy(VisionProvider.MOCK),
    )
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}
    return AppState(
        settings=settings,
        encryptor=encryptor,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=LocalBlobStore(settings.blob_local_root),
        vision_router=router,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
        queue=InMemoryQueue(),
        sla_presets=dict(SLA_PRESETS),
    )


@pytest.fixture
def sync_client(
    settings: Settings,
    seeded: dict[str, Any],
) -> Iterator[Client]:
    """Drive the SDK against an in-process FastAPI app.

    starlette's TestClient is a sync httpx.Client over the ASGI app —
    perfect for testing the SDK's sync path. Must override AppState
    *after* TestClient enters the lifespan, otherwise the lifespan
    rebuilds it.
    """
    from starlette.testclient import TestClient  # noqa: PLC0415

    app = create_app(settings=settings)
    test_client = TestClient(app)
    test_client.__enter__()
    app.state.app_state = _build_app_state(settings)
    try:
        sdk_client = Client(
            base_url=str(test_client.base_url).rstrip("/"),
            api_key=seeded["api_key"],
            http_client=test_client,
        )
        yield sdk_client
    finally:
        test_client.__exit__(None, None, None)


@pytest.fixture
async def async_client(
    settings: Settings,
    seeded: dict[str, Any],
) -> AsyncIterator[AsyncClient]:
    """Drive the SDK's async path through httpx.ASGITransport.

    Bypasses the lifespan event (no startup/shutdown), so we can attach
    AppState before any request arrives.
    """
    app = create_app(settings=settings)
    app.state.app_state = _build_app_state(settings)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        client = AsyncClient(
            base_url="http://test",
            api_key=seeded["api_key"],
            http_client=http,
        )
        yield client


# ─── Sync tests ──────────────────────────────────────────────
def test_sync_create_transcript_round_trip(sync_client: Client) -> None:
    resp = sync_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    assert resp.job.status == "succeeded"
    assert resp.overall_confidence == 0.95
    assert resp.extraction["student"]["full_name"] == "Jan Kowalski"


def test_sync_get_job_and_result(sync_client: Client) -> None:
    create = sync_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    job = sync_client.jobs.get(create.job.id)
    assert job.status == "succeeded"
    blob = sync_client.jobs.get_result(create.job.id)
    # xlsx files start with the PK\x03\x04 ZIP magic.
    assert blob[:2] == b"PK"


def test_sync_list_jobs(sync_client: Client) -> None:
    sync_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    jobs = sync_client.jobs.list(limit=10)
    assert len(jobs) >= 1


def test_sync_templates(sync_client: Client) -> None:
    resp = sync_client.templates.list()
    assert any(t.target_id == "us-hs.v1" for t in resp.targets)


def test_sync_usage(sync_client: Client) -> None:
    sync_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    usage = sync_client.usage.get()
    assert usage.transcripts_processed >= 1


def test_sync_webhook_create_and_list(sync_client: Client) -> None:
    created = sync_client.webhooks.create(
        url="https://example.com/hook",
        events=["job.completed"],
    )
    assert len(created.signing_secret) == 64

    rows = sync_client.webhooks.list()
    assert any(w.url == "https://example.com/hook" for w in rows)


def test_sync_unauthenticated_raises_typed_error(settings: Settings, db_setup: None) -> None:
    """Bad API key should raise AuthenticationError."""
    _ = db_setup
    from starlette.testclient import TestClient  # noqa: PLC0415

    app = create_app(settings=settings)
    test_client = TestClient(app)
    test_client.__enter__()
    app.state.app_state = _build_app_state(settings)
    try:
        client = Client(
            base_url=str(test_client.base_url).rstrip("/"),
            api_key="sk_test_invalid",
            http_client=test_client,
        )
        with pytest.raises(AuthenticationError) as exc:
            client.transcripts.create(
                file_bytes=_png(),
                filename="t.png",
                profile_id="pl.lo.swiadectwo_szkolne.v1",
                target_id="us-hs.v1",
                content_type="image/png",
            )
        assert exc.value.status == 401
    finally:
        test_client.__exit__(None, None, None)


# ─── Async tests ─────────────────────────────────────────────
@pytest.mark.asyncio
async def test_async_create_transcript_round_trip(async_client: AsyncClient) -> None:
    resp = await async_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    assert resp.job.status == "succeeded"
    assert resp.extraction["student"]["full_name"] == "Jan Kowalski"


@pytest.mark.asyncio
async def test_async_jobs_and_templates(async_client: AsyncClient) -> None:
    create = await async_client.transcripts.create(
        file_bytes=_png(),
        filename="t.png",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        content_type="image/png",
    )
    job = await async_client.jobs.get(create.job.id)
    assert job.status == "succeeded"
    templates = await async_client.templates.list()
    assert any(t.target_id == "us-hs.v1" for t in templates.targets)


@pytest.mark.asyncio
async def test_async_batch_endpoint_returns_202(async_client: AsyncClient) -> None:
    resp = await async_client.transcripts.create_batch(
        files=[
            ("a.png", _png(), "image/png"),
            ("b.png", _png(), "image/png"),
        ],
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
    )
    assert resp.accepted_count == 2
    assert len(resp.jobs) == 2


# ─── ForbiddenError import-only smoke ────────────────────────
def test_forbidden_error_class_exists() -> None:
    """ForbiddenError is part of the public surface used by economy
    tier callers; import-only smoke."""
    assert issubclass(ForbiddenError, Exception)

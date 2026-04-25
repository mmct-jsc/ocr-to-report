"""Phase 7 — POST /v1/transcripts:batch endpoint tests.

Validates the API contract:

* Multiple files accepted in one request.
* 202 status with per-job summaries.
* Oversized uploads rejected (with reason).
* A BATCH_SUBMIT envelope is enqueued for the worker.
* Each accepted job is created with kind='batch', status='pending',
  pipeline_id='batch_economy_v1'.
"""

from __future__ import annotations

import base64
import io
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
from ocr_to_report.adapters.queue import InMemoryQueue, TaskKind
from ocr_to_report.adapters.vision import (
    FixedPolicy,
    InMemoryAsyncCache,
    ProviderRouter,
    VisionProvider,
)
from ocr_to_report.api.app import create_app
from ocr_to_report.api.deps import AppState
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


def _png(size: tuple[int, int] = (400, 600)) -> bytes:
    img = PILImage.new("RGB", size, color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(
        "OCR2R_KEK_B64",
        base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
    )
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    return Settings(
        env="development",
        database_url=db_url,
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
        tenant_repo = TenantRepo(session, encryptor)
        tenant, _dek = await tenant_repo.create(name="Acme", slug="acme")
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key}


class _StubVisionAdapter:
    name = VisionProvider.MOCK

    async def extract(self, _request: Any) -> Any:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


@pytest.fixture
def client_and_queue(
    settings: Settings,
    seeded: dict[str, Any],
) -> Iterator[tuple[TestClient, InMemoryQueue]]:
    app = create_app(settings=settings)
    router = ProviderRouter(
        {VisionProvider.MOCK: _StubVisionAdapter()},
        FixedPolicy(VisionProvider.MOCK),
    )
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}
    queue = InMemoryQueue()
    with TestClient(app) as c:
        from ocr_to_report.core.sla import SLA_PRESETS  # noqa: PLC0415

        app.state.app_state = AppState(
            settings=settings,
            encryptor=encryptor,
            profile_registry=profile_registry,
            target_registry=target_registry,
            blob_store=LocalBlobStore(settings.blob_local_root),
            vision_router=router,
            result_cache=InMemoryAsyncCache(),
            bundle_roots=bundle_roots,
            queue=queue,
            sla_presets=dict(SLA_PRESETS),
        )
        yield c, queue


def test_batch_endpoint_accepts_multiple_files_and_enqueues(
    client_and_queue: tuple[TestClient, InMemoryQueue],
    seeded: dict[str, Any],
) -> None:
    client, queue = client_and_queue
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    files = [
        ("files", ("a.png", _png(), "image/png")),
        ("files", ("b.png", _png(), "image/png")),
        ("files", ("c.png", _png(), "image/png")),
    ]
    r = client.post(
        "/v1/transcripts:batch",
        headers=headers,
        files=files,
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted_count"] == 3
    assert len(body["jobs"]) == 3
    for summary in body["jobs"]:
        assert summary["pipeline_id"] == "batch_economy_v1"
        assert summary["status"] == "pending"
    assert body["rejected"] == []

    # The endpoint enqueued one BATCH_SUBMIT envelope (and a delayed
    # RETENTION_SWEEP). pending_count() returns just the visible ones,
    # which is the BATCH_SUBMIT.
    assert queue.pending_count() == 1


def test_batch_endpoint_rejects_oversized_files(
    client_and_queue: tuple[TestClient, InMemoryQueue],
    seeded: dict[str, Any],
) -> None:
    client, _queue = client_and_queue
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    huge = b"\x00" * (26 * 1024 * 1024)
    files = [
        ("files", ("big.bin", huge, "application/octet-stream")),
        ("files", ("small.png", _png(), "image/png")),
    ]
    r = client.post(
        "/v1/transcripts:batch",
        headers=headers,
        files=files,
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["accepted_count"] == 1
    assert len(body["rejected"]) == 1
    assert "big.bin" in body["rejected"][0]


def test_batch_endpoint_rejects_when_all_oversized(
    client_and_queue: tuple[TestClient, InMemoryQueue],
    seeded: dict[str, Any],
) -> None:
    client, _queue = client_and_queue
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    huge = b"\x00" * (26 * 1024 * 1024)
    files = [("files", ("big.bin", huge, "application/octet-stream"))]
    r = client.post(
        "/v1/transcripts:batch",
        headers=headers,
        files=files,
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 413


def test_batch_endpoint_rejects_unauthenticated(
    client_and_queue: tuple[TestClient, InMemoryQueue],
) -> None:
    client, _queue = client_and_queue
    r = client.post(
        "/v1/transcripts:batch",
        files=[("files", ("a.png", _png(), "image/png"))],
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 401


def test_batch_endpoint_validates_task_kind_in_queue(
    client_and_queue: tuple[TestClient, InMemoryQueue],
    seeded: dict[str, Any],
) -> None:
    """The queued envelope is BATCH_SUBMIT with the tenant_id payload."""
    client, queue = client_and_queue
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/transcripts:batch",
        headers=headers,
        files=[("files", ("a.png", _png(), "image/png"))],
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 202

    import asyncio  # noqa: PLC0415

    async def _drain() -> Any:
        return await queue.lease(timeout_seconds=0.5)

    envelope = asyncio.run(_drain())
    assert envelope is not None
    assert envelope.kind is TaskKind.BATCH_SUBMIT
    assert envelope.payload["tenant_id"] == str(seeded["tenant_id"])

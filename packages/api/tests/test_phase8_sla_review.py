"""Phase 8 — SLA gating + manual-review queue end-to-end.

Demo artifact: a Premium tenant (0.95 threshold) has a low-confidence
extraction parked, the reviewer lists the parked queue, approves it
(re-extracts at higher confidence), and the rendered xlsx is
downloadable.

Also covers:
* Economy tier rejecting sync /v1/transcripts (should redirect to batch).
* Standard tier completing normally when confidence ≥ 0.85.
* Reject endpoint marks the parked job failed.
"""

from __future__ import annotations

import base64
import io
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
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
from ocr_to_report.core.sla import SLA_PRESETS, SlaTier
from ocr_to_report.core.targets import TargetRegistry

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
            {"raw_subject_name": "Język polski", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Fizyka", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Chemia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Biologia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Geografia", "raw_grade_value": "dobry"},
            {"raw_subject_name": "Informatyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Wychowanie fizyczne", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język angielski IV.1r.", "raw_grade_value": "bardzo dobry"},
        ],
        "advanced_subjects": ["Język angielski"],
    }


class _ToggleVisionAdapter:
    """Vision adapter that emits configurable confidence on each call.

    First call emits ``low_confidence``; subsequent calls emit
    ``high_confidence``. Lets us test the park-then-approve flow with
    a single fixture.
    """

    name = VisionProvider.MOCK

    def __init__(self, *, low: float, high: float) -> None:
        self._low = low
        self._high = high
        self._call_count = 0
        self.extract = AsyncMock(side_effect=self._extract)

    async def _extract(self, _request: Any) -> ExtractionResult:
        self._call_count += 1
        confidence = self._low if self._call_count == 1 else self._high
        return ExtractionResult(
            raw_extraction=_polish_extraction(),
            confidence=confidence,
            field_confidences=None,
            warnings=[],
            provider=VisionProvider.MOCK,
            model_id="mock",
            usage=TokenUsage(input_tokens=1500, output_tokens=300, usd_cost=0.003),
        )

    async def aclose(self) -> None:
        return None


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


async def _seed_tenant(
    settings: Settings,
    *,
    sla_tier: SlaTier,
) -> dict[str, Any]:
    """Insert a tenant on the given SLA tier + an API key; return creds."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name=f"Acme-{sla_tier.value}", slug=sla_tier.value)
        # Override the SLA tier — the repo defaults to "standard".
        tenant.sla_tier = sla_tier.value
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key, "tier": sla_tier.value}


def _make_client(
    settings: Settings,
    *,
    adapter: Any,
) -> TestClient:
    """Build a TestClient with the given (test) vision adapter wired in."""
    app = create_app(settings=settings)
    router = ProviderRouter(
        {VisionProvider.MOCK: adapter},
        FixedPolicy(VisionProvider.MOCK),
    )
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}

    client = TestClient(app)
    client.__enter__()
    app.state.app_state = AppState(
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
    return client


@pytest.fixture
async def premium_client(
    settings: Settings,
    db_setup: None,
) -> AsyncIterator[tuple[TestClient, dict[str, Any], _ToggleVisionAdapter]]:
    """Premium tenant (0.95 threshold) + a toggle vision adapter."""
    seeded = await _seed_tenant(settings, sla_tier=SlaTier.PREMIUM)
    adapter = _ToggleVisionAdapter(low=0.90, high=0.97)
    client = _make_client(settings, adapter=adapter)
    try:
        yield client, seeded, adapter
    finally:
        client.__exit__(None, None, None)


def test_premium_low_confidence_parks_then_approve_completes(
    premium_client: tuple[TestClient, dict[str, Any], _ToggleVisionAdapter],
) -> None:
    """Demo artifact: park → list → approve → render."""
    client, seeded, _adapter = premium_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    # 1. POST /v1/transcripts with the low-confidence first response → parked.
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["status"] == "parked"
    assert body["overall_confidence"] == 0.90
    job_id = body["job"]["id"]
    assert any("parked" in w for w in body["warnings"])

    # 2. GET /v1/jobs?status=parked lists it.
    r2 = client.get("/v1/jobs?status=parked", headers=headers)
    assert r2.status_code == 200
    parked_list = r2.json()
    assert any(job["id"] == job_id for job in parked_list)
    parked = next(job for job in parked_list if job["id"] == job_id)
    assert parked["park_reason"] is not None
    assert "below SLA tier" in parked["park_reason"]

    # 3. POST /v1/jobs/{id}/approve → re-extract (now at 0.97), render, complete.
    r3 = client.post(f"/v1/jobs/{job_id}/approve", headers=headers)
    assert r3.status_code == 200, r3.text
    approved = r3.json()
    assert approved["status"] == "succeeded"
    assert approved["output_blob_key"] is not None

    # 4. GET /v1/jobs/{id}/result returns the xlsx.
    r4 = client.get(f"/v1/jobs/{job_id}/result", headers=headers)
    assert r4.status_code == 200
    assert r4.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


def test_reject_marks_parked_job_failed(
    premium_client: tuple[TestClient, dict[str, Any], _ToggleVisionAdapter],
) -> None:
    client, seeded, _adapter = premium_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200
    job_id = r.json()["job"]["id"]
    assert r.json()["job"]["status"] == "parked"

    r2 = client.post(
        f"/v1/jobs/{job_id}/reject",
        headers=headers,
        json={"reason": "image illegible"},
    )
    assert r2.status_code == 200
    assert r2.json()["status"] == "failed"
    assert r2.json()["error_detail"] == "image illegible"


def test_approving_unparked_job_returns_409(
    premium_client: tuple[TestClient, dict[str, Any], _ToggleVisionAdapter],
) -> None:
    client, seeded, adapter = premium_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    # Force the adapter to return a high-confidence result first time, so
    # the job reaches succeeded and is no longer parkable.
    adapter._low = 0.97
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200
    assert r.json()["job"]["status"] == "succeeded"
    job_id = r.json()["job"]["id"]

    r2 = client.post(f"/v1/jobs/{job_id}/approve", headers=headers)
    assert r2.status_code == 409


@pytest.fixture
async def economy_client(
    settings: Settings,
    db_setup: None,
) -> AsyncIterator[tuple[TestClient, dict[str, Any]]]:
    seeded = await _seed_tenant(settings, sla_tier=SlaTier.ECONOMY)
    adapter = _ToggleVisionAdapter(low=0.97, high=0.97)
    client = _make_client(settings, adapter=adapter)
    try:
        yield client, seeded
    finally:
        client.__exit__(None, None, None)


def test_economy_tier_rejects_sync_transcripts_with_403(
    economy_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = economy_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["status"] == 403
    assert "economy" in body["detail"].lower()
    assert "batch" in body["detail"].lower()


@pytest.fixture
async def standard_client(
    settings: Settings,
    db_setup: None,
) -> AsyncIterator[tuple[TestClient, dict[str, Any]]]:
    seeded = await _seed_tenant(settings, sla_tier=SlaTier.STANDARD)
    adapter = _ToggleVisionAdapter(low=0.90, high=0.97)
    client = _make_client(settings, adapter=adapter)
    try:
        yield client, seeded
    finally:
        client.__exit__(None, None, None)


def test_standard_tier_completes_at_0_90_confidence(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Standard threshold is 0.85 — 0.90 is fine."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200
    assert r.json()["job"]["status"] == "succeeded"

"""End-to-end: tenant SLA overrides actually influence live jobs.

The core override resolver was shipped in v0.2.0 Task 3 — this is the
proof that the API layer wires it into the request pipeline. A
Standard-tier tenant normally has ``confidence_threshold == 0.85`` (so
a 0.90 extraction is auto-rendered). With a single override patch
bumping that threshold to 0.95, the same vision result must instead
park the job for manual review.

The test mirrors the structure of ``test_phase8_sla_review.py`` so the
shared seed/client/adapter helpers stay obvious — only the override row
insertion + the assertion shape are new.
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
from ocr_to_report.adapters.db.repositories import (
    ApiKeyRepo,
    TenantOverrideRepo,
    TenantRepo,
)
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


# ─── helpers (mirroring test_phase8_sla_review.py shape) ──────────────


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


class _FixedConfidenceVisionAdapter:
    """Vision adapter that always returns a given confidence value.

    Simpler than the toggle adapter — this test doesn't need approve →
    re-extract; it just proves the threshold from the OVERRIDE is what
    gates the park decision.
    """

    name = VisionProvider.MOCK

    def __init__(self, confidence: float) -> None:
        self._confidence = confidence
        self.extract = AsyncMock(side_effect=self._extract)

    async def _extract(
        self, _request: Any, *, override_api_key: str | None = None
    ) -> ExtractionResult:
        del override_api_key  # v0.3.0 BYOK threading; mock doesn't care
        return ExtractionResult(
            raw_extraction=_polish_extraction(),
            confidence=self._confidence,
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


async def _seed_standard_tenant_with_threshold_override(
    settings: Settings,
    *,
    overridden_threshold: float,
) -> dict[str, Any]:
    """Seed a STANDARD-tier tenant + one SLA-scoped override row.

    The override pushes ``confidence_threshold`` to ``overridden_threshold``
    so the test can pick a value that flips park vs complete for a known
    vision confidence.
    """
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name="Acme Std", slug="acme-std")
        tenant.sla_tier = SlaTier.STANDARD.value
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        # The override: bump confidence_threshold on top of the Standard preset.
        overrides = TenantOverrideRepo(session)
        await overrides.upsert(
            tenant_id=tenant.id,
            scope="sla",
            target_id=None,
            patches=[
                {"op": "set", "path": "confidence_threshold", "value": overridden_threshold},
            ],
        )
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key}


def _make_client(
    settings: Settings,
    *,
    adapter: Any,
) -> TestClient:
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


# ─── the canonical Task 4 proof ───────────────────────────────────────


async def test_sla_override_bumps_threshold_and_parks_job(
    settings: Settings, db_setup: None
) -> None:
    """Standard tier + SLA override ``confidence_threshold = 0.95``.

    Vision returns 0.90. Without the override, Standard tier (threshold
    0.85) would auto-render. WITH the override the request must park.
    """
    seeded = await _seed_standard_tenant_with_threshold_override(
        settings, overridden_threshold=0.95
    )
    adapter = _FixedConfidenceVisionAdapter(confidence=0.90)
    client = _make_client(settings, adapter=adapter)
    try:
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
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["job"]["status"] == "parked", (
            "expected the override-bumped threshold (0.95) to park the 0.90 extraction; "
            f"job status was {body['job']['status']!r} — override wire likely missing"
        )
        assert body["overall_confidence"] == 0.90
    finally:
        client.__exit__(None, None, None)


async def test_no_override_uses_base_tier_threshold(settings: Settings, db_setup: None) -> None:
    """Companion control: same vision confidence, no override → completes.

    Without the override row, the Standard preset's 0.85 threshold lets
    the 0.90 extraction through. This proves the resolver isn't somehow
    bumping the threshold in the absence of an override (defense against
    a stale fixture or accidentally-shared state).
    """
    # Seed the same tenant shape but DON'T insert the override row.
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _ = await tenants.create(name="Acme Plain Std", slug="acme-plain-std")
        tenant.sla_tier = SlaTier.STANDARD.value
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        await session.commit()

    adapter = _FixedConfidenceVisionAdapter(confidence=0.90)
    client = _make_client(settings, adapter=adapter)
    try:
        headers = {"Authorization": f"Bearer {plain_key}"}
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
        assert body["job"]["status"] == "succeeded", (
            f"no override + Standard tier threshold (0.85) should not park 0.90; "
            f"got status {body['job']['status']!r}"
        )
    finally:
        client.__exit__(None, None, None)


# AsyncIterator import is for type checking in shared helpers.
_ = AsyncIterator

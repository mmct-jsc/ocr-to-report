"""Phase 11 — GDPR DSR endpoints + magic-byte upload validation."""

from __future__ import annotations

import base64
import io
import secrets
from collections.abc import Iterator
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
from ocr_to_report.core.sla import SLA_PRESETS
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


def _png() -> bytes:
    img = PILImage.new("RGB", (400, 600), color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _polish_extraction(name: str = "Jan Kowalski") -> dict[str, Any]:
    return {
        "full_name": name,
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


class _NameVisionAdapter:
    """Vision adapter that emits a configurable subject name per call."""

    name = VisionProvider.MOCK

    def __init__(self) -> None:
        self.next_name = "Jan Kowalski"
        self.extract = AsyncMock(side_effect=self._extract)

    async def _extract(self, _request: Any) -> ExtractionResult:
        return ExtractionResult(
            raw_extraction=_polish_extraction(self.next_name),
            confidence=0.95,
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


@pytest.fixture
def client_with_adapter(
    settings: Settings,
    seeded: dict[str, Any],
) -> Iterator[tuple[TestClient, _NameVisionAdapter]]:
    app = create_app(settings=settings)
    adapter = _NameVisionAdapter()
    router = ProviderRouter(
        {VisionProvider.MOCK: adapter},
        FixedPolicy(VisionProvider.MOCK),
    )
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}
    with TestClient(app) as c:
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
        yield c, adapter


def _create_transcript(client: TestClient, headers: dict[str, str]) -> str:
    """Helper: POST a transcript and return the job id."""
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
    return str(r.json()["job"]["id"])


# ─── DSR endpoint behavior ───────────────────────────────────
def test_dsr_access_returns_matching_transcripts(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    """A single transcript for Jan should be retrievable by DSR access."""
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    _create_transcript(client, headers)

    r = client.get(
        "/v1/dsr/access",
        headers=headers,
        params={"subject_full_name": "Jan Kowalski"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["subject_full_name"] == "Jan Kowalski"
    assert body["record_count"] == 1
    assert len(body["transcripts"]) == 1
    assert body["transcripts"][0]["student"]["full_name"] == "Jan Kowalski"


def test_dsr_access_case_insensitive_match(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    _create_transcript(client, headers)

    r = client.get(
        "/v1/dsr/access",
        headers=headers,
        params={"subject_full_name": "JAN KOWALSKI"},
    )
    assert r.status_code == 200
    assert r.json()["record_count"] == 1


def test_dsr_access_with_no_matches_returns_empty(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.get(
        "/v1/dsr/access",
        headers=headers,
        params={"subject_full_name": "Ghost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["record_count"] == 0
    assert body["transcripts"] == []


def test_dsr_portability_carries_schema_version(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    _create_transcript(client, headers)

    r = client.get(
        "/v1/dsr/portability",
        headers=headers,
        params={"subject_full_name": "Jan Kowalski"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "dsr.portability.v1"
    assert len(body["transcripts"]) == 1


def test_dsr_erasure_removes_transcript_and_blobs(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    job_id = _create_transcript(client, headers)
    # Sanity: result blob is downloadable before erasure.
    r1 = client.get(f"/v1/jobs/{job_id}/result", headers=headers)
    assert r1.status_code == 200

    r2 = client.post(
        "/v1/dsr/erasure",
        headers=headers,
        json={"subject_full_name": "Jan Kowalski", "confirm": True},
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["transcripts_erased"] >= 1
    assert body["blobs_erased"] >= 1

    # Access call after erasure: 0 records.
    r3 = client.get(
        "/v1/dsr/access",
        headers=headers,
        params={"subject_full_name": "Jan Kowalski"},
    )
    assert r3.status_code == 200
    assert r3.json()["record_count"] == 0

    # Result-blob endpoint is now 404 (output_blob_key was nulled).
    r4 = client.get(f"/v1/jobs/{job_id}/result", headers=headers)
    assert r4.status_code == 404


def test_dsr_erasure_requires_confirm_flag(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.post(
        "/v1/dsr/erasure",
        headers=headers,
        json={"subject_full_name": "Jan Kowalski", "confirm": False},
    )
    # Pydantic rejects confirm != True via the Literal[True] type.
    assert r.status_code == 400


def test_dsr_appends_audit_log_entries(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
    settings: Settings,
) -> None:
    """Each DSR action appends a row tagged ``ferpa_disclosure=True``."""
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    _create_transcript(client, headers)
    client.get(
        "/v1/dsr/access",
        headers=headers,
        params={"subject_full_name": "Jan Kowalski"},
    )

    import asyncio  # noqa: PLC0415

    from sqlalchemy import select  # noqa: PLC0415

    from ocr_to_report.adapters.db.models import AuditLog  # noqa: PLC0415

    async def _query() -> list[AuditLog]:
        sm = get_sessionmaker(settings.database_url)
        async with sm() as session:
            result = await session.execute(select(AuditLog).where(AuditLog.action.like("dsr.%")))
            return list(result.scalars().all())

    rows = asyncio.run(_query())
    assert any(r.action == "dsr.access" for r in rows)
    assert any(
        r.metadata_json.get("ferpa_disclosure") is True for r in rows if r.action == "dsr.access"
    )


# ─── Magic-byte upload validation ────────────────────────────
def test_post_transcripts_rejects_non_image_blob(
    client_with_adapter: tuple[TestClient, _NameVisionAdapter],
    seeded: dict[str, Any],
) -> None:
    """A blob with no recognized magic bytes is rejected with 415."""
    client, _adapter = client_with_adapter
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", b"NOT-A-REAL-IMAGE\x00\x00\x00\x00", "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 415, r.text
    body = r.json()
    assert body["status"] == 415
    assert "type" in body

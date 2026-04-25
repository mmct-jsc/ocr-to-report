"""Phase 6 — end-to-end API integration test.

Exercises POST /v1/transcripts → GET /v1/jobs/{id} → GET
/v1/jobs/{id}/result → GET /v1/usage with a real FastAPI TestClient,
real SQLite database, real Polish profile + US-HS target bundles, and
a mocked Anthropic vision adapter.
"""

from __future__ import annotations

import base64
import io
import json
import secrets
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from PIL import Image as PILImage
from sqlalchemy import text

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
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
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


def _polish_grade9_raw_extraction() -> dict[str, Any]:
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
            {"raw_subject_name": "Język angielski IV.1r.", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język francuski IV.1p.", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Filozofia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Fizyka", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Chemia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Biologia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Geografia", "raw_grade_value": "dobry"},
            {"raw_subject_name": "Informatyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Wychowanie fizyczne", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Edukacja dla bezpieczeństwa", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Biznes i zarządzanie", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia i teraźniejszość", "raw_grade_value": "celujący"},
        ],
        "advanced_subjects": ["Język angielski", "Geografia", "Matematyka", "Fizyka"],
    }


def _make_png_bytes() -> bytes:
    img = PILImage.new("RGB", (800, 1200), color=(240, 240, 220))
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
    """Insert a tenant + API key; return the plain key for auth."""
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


@pytest.fixture
def client(settings: Settings, seeded: dict[str, Any]) -> Iterator[TestClient]:
    """Build the app with mocked vision; yield TestClient."""
    app = create_app(settings=settings)

    # Replace the vision router with a mock that returns canned extraction.
    raw = _polish_grade9_raw_extraction()
    mock_adapter = _MockVisionAdapter(raw)
    router = ProviderRouter(
        {VisionProvider.MOCK: mock_adapter},
        FixedPolicy(VisionProvider.MOCK),
    )

    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}

    with TestClient(app) as c:
        # Override the lifespan-built app_state with one wired to our
        # mock vision adapter. Must happen *after* TestClient enters the
        # lifespan, otherwise the lifespan rebuilds and overwrites.
        from ocr_to_report.adapters.queue import InMemoryQueue  # noqa: PLC0415

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
        )
        yield c


class _MockVisionAdapter:
    name = VisionProvider.MOCK

    def __init__(self, raw: dict[str, Any]) -> None:
        self.extract = AsyncMock(
            return_value=ExtractionResult(
                raw_extraction=raw,
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


# ─── Tests ────────────────────────────────────────────────────
def test_health_unauthenticated_works(client: TestClient) -> None:
    r = client.get("/v1/health")
    assert r.status_code == 200


def test_unauthenticated_request_rejected(client: TestClient) -> None:
    r = client.post(
        "/v1/transcripts",
        files={"file": ("t.png", _make_png_bytes(), "image/png")},
        data={"profile_id": "pl.lo.swiadectwo_szkolne.v1", "target_id": "us-hs.v1"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["status"] == 401
    assert body["type"].endswith("/unauthorized")
    assert r.headers["www-authenticate"] == "Bearer"
    assert r.headers["content-type"].startswith("application/problem+json")


def test_post_transcripts_full_flow(
    client: TestClient,
    seeded: dict[str, Any],
) -> None:
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _make_png_bytes(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["overall_confidence"] == 0.95
    assert body["job"]["status"] == "succeeded"
    assert body["extraction"]["student"]["full_name"] == "Jan Kowalski"
    job_id = body["job"]["id"]

    # GET /v1/jobs/{id}
    r2 = client.get(f"/v1/jobs/{job_id}", headers=headers)
    assert r2.status_code == 200
    assert r2.json()["status"] == "succeeded"

    # GET /v1/jobs/{id}/result returns the xlsx
    r3 = client.get(f"/v1/jobs/{job_id}/result", headers=headers)
    assert r3.status_code == 200
    assert r3.headers["content-type"].startswith(
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    workbook = load_workbook(filename=io.BytesIO(r3.content))
    sheet = workbook.active
    assert sheet["A2"].value == "Jan Kowalski"
    assert sheet["D19"].value == "A+"  # math celujący
    assert sheet["E19"].value == "135h"  # math advanced

    # GET /v1/usage shows the rollup
    r4 = client.get("/v1/usage", headers=headers)
    assert r4.status_code == 200
    usage = r4.json()
    assert usage["transcripts_processed"] == 1
    assert usage["tokens_input"] == 1500
    assert usage["tokens_output"] == 300


def test_post_webhook_returns_secret(
    client: TestClient,
    seeded: dict[str, Any],
) -> None:
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.post(
        "/v1/webhooks",
        headers=headers,
        json={"url": "https://example.com/hook", "events": ["job.completed"]},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["url"] == "https://example.com/hook"
    assert "signing_secret" in body
    assert len(body["signing_secret"]) == 64  # 32 bytes hex-encoded

    # GET /v1/webhooks lists it (without secret)
    r2 = client.get("/v1/webhooks", headers=headers)
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) == 1
    assert "signing_secret" not in rows[0]


def test_get_templates_lists_us_hs(client: TestClient, seeded: dict[str, Any]) -> None:
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.get("/v1/templates", headers=headers)
    assert r.status_code == 200
    targets = r.json()["targets"]
    assert any(t["target_id"] == "us-hs.v1" for t in targets)
    us_hs = next(t for t in targets if t["target_id"] == "us-hs.v1")
    assert any(tpl["key"] == "grade_9" for tpl in us_hs["templates"])


def test_problem_detail_format_on_validation_error(
    client: TestClient, seeded: dict[str, Any]
) -> None:
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    # Missing profile_id form field
    r = client.post(
        "/v1/transcripts",
        headers=headers,
        files={"file": ("t.png", _make_png_bytes(), "image/png")},
        data={"target_id": "us-hs.v1"},
    )
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert body["type"].endswith("/validation")
    assert body["status"] == 400


# Suppress unused-imports for variables used only in type narrowing.
_ = (text, json, uuid)

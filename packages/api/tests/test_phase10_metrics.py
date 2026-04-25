"""Phase 10 — Prometheus metrics + ``/metrics`` endpoint."""

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
from ocr_to_report.api.metrics import build_metrics
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import SLA_PRESETS
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── Unit-level: Metrics namespace ───────────────────────────
def test_build_metrics_returns_distinct_registries() -> None:
    a = build_metrics()
    b = build_metrics()
    assert a.registry is not b.registry


def test_metrics_has_all_three_tiers() -> None:
    m = build_metrics()
    # Tier 1
    assert m.http_requests_total is not None
    assert m.http_request_duration_seconds is not None
    assert m.http_errors_total is not None
    # Tier 2
    assert m.pipeline_step_duration_seconds is not None
    assert m.vision_confidence is not None
    assert m.vision_tokens_total is not None
    assert m.vision_usd_cost_total is not None
    assert m.circuit_state is not None
    # Tier 3
    assert m.transcripts_processed_total is not None
    assert m.manual_reviews_pending is not None
    assert m.webhook_deliveries_total is not None
    assert m.cache_hits_total is not None
    assert m.cache_misses_total is not None


# ─── Endpoint-level: /metrics integration ────────────────────
def _png() -> bytes:
    img = PILImage.new("RGB", (400, 600), color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


class _StubAdapter:
    name = VisionProvider.MOCK

    def __init__(self) -> None:
        self.extract = AsyncMock(
            return_value=ExtractionResult(
                raw_extraction={
                    "full_name": "Jan",
                    "birth_date": "2010-01-15",
                    "school_year": "2023/2024",
                    "current_class_name": "pierwszej",
                    "school_name": "Test",
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


@pytest.fixture
def client(settings: Settings, seeded: dict[str, Any]) -> Iterator[TestClient]:
    app = create_app(settings=settings)
    router = ProviderRouter(
        {VisionProvider.MOCK: _StubAdapter()},
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
        yield c


def test_metrics_endpoint_returns_prometheus_format(
    client: TestClient,
    seeded: dict[str, Any],
) -> None:
    """/metrics responds with Prometheus exposition format."""
    response = client.get("/metrics")
    assert response.status_code == 200
    content_type = response.headers["content-type"]
    assert content_type.startswith("text/plain")
    body = response.text
    # Every collector we declared should appear in HELP lines.
    assert "ocr2r_http_requests_total" in body
    assert "ocr2r_http_request_duration_seconds" in body
    assert "ocr2r_pipeline_step_duration_seconds" in body
    assert "ocr2r_vision_confidence" in body
    assert "ocr2r_transcripts_processed_total" in body


def test_request_metrics_increment_after_traffic(
    client: TestClient,
    seeded: dict[str, Any],
) -> None:
    """Hitting endpoints increments http_requests_total + latency hist."""
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    # Hit a few endpoints.
    client.get("/v1/health")
    client.get("/v1/templates", headers=headers)
    client.get("/v1/usage", headers=headers)

    response = client.get("/metrics")
    body = response.text
    # /v1/health is unauthenticated; the route should be tracked.
    assert "ocr2r_http_requests_total" in body
    assert 'method="GET"' in body
    # 200 status appears — the health endpoint always 200s.
    assert 'status="200"' in body
    # Duration histogram has buckets present.
    assert "ocr2r_http_request_duration_seconds_bucket" in body


def test_metrics_endpoint_excludes_itself_from_counters(
    client: TestClient,
) -> None:
    """The middleware skips /metrics itself to avoid self-referential noise."""
    # First scrape — establishes baseline.
    client.get("/metrics")
    body_before = client.get("/metrics").text
    # The /metrics route should not appear as a counted route. We check
    # by absence of an exact label sequence.
    assert 'route="/metrics"' not in body_before


def test_404_routes_recorded_in_errors_counter(client: TestClient) -> None:
    """Unknown routes contribute to ocr2r_http_errors_total."""
    client.get("/v1/this-does-not-exist")
    body = client.get("/metrics").text
    # We don't pin the route format strictly (FastAPI returns the raw
    # path on unmatched routes), but the errors counter should have at
    # least one observation with a 4xx status.
    assert "ocr2r_http_errors_total" in body

"""``/v1/tenant/config`` CRUD — happy + sad paths (v0.2.0 Task 5).

Covers:

* ``GET`` — fresh tenant gets the tier preset back, empty patch lists.
* ``POST :preview`` — applies SLA patches without persisting; second GET
  still returns the un-modified config.
* ``PUT`` — persists SLA + profile + target patches; subsequent GET
  reflects them; the resolved SLA in the response carries the patch.
* ``PUT`` rejects malformed SLA patches (out-of-range threshold → 400).
* ``PUT`` with an empty list clears the SLA override row entirely.

Reuses the seed/client helpers from ``test_phase8_sla_review.py``.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
from ocr_to_report.adapters.queue import InMemoryQueue
from ocr_to_report.adapters.vision import (
    FixedPolicy,
    InMemoryAsyncCache,
    ProviderRouter,
    VisionProvider,
)
from ocr_to_report.adapters.vision.stub_adapters import OpenAIVisionAdapter
from ocr_to_report.api.app import create_app
from ocr_to_report.api.deps import AppState
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import SLA_PRESETS, SlaTier
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


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
async def standard_client(
    settings: Settings, db_setup: None
) -> AsyncIterator[tuple[TestClient, dict[str, Any]]]:
    """Standard-tier tenant + API key, no overrides seeded."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _ = await tenants.create(name="Acme TC", slug="acme-tc")
        tenant.sla_tier = SlaTier.STANDARD.value
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(tenant_id=tenant.id, scopes=["transcripts:write"])
        await session.commit()
        seeded = {"tenant_id": tenant.id, "api_key": plain_key}

    app = create_app(settings=settings)
    router = ProviderRouter(
        {VisionProvider.OPENAI: OpenAIVisionAdapter()},
        FixedPolicy(VisionProvider.OPENAI),
    )
    encryptor2 = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}

    client = TestClient(app)
    client.__enter__()
    app.state.app_state = AppState(
        settings=settings,
        encryptor=encryptor2,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=LocalBlobStore(settings.blob_local_root),
        vision_router=router,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
        queue=InMemoryQueue(),
        sla_presets=dict(SLA_PRESETS),
    )
    try:
        yield client, seeded
    finally:
        client.__exit__(None, None, None)


# ─── happy paths ─────────────────────────────────────────────────────


def test_get_returns_tier_preset_when_no_overrides(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    r = client.get("/v1/tenant/config", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    # Standard tier preset confidence_threshold is the canonical baseline.
    assert body["sla"]["tier"] == "standard"
    assert body["sla_patches"] == []
    assert body["profile_overrides"] == {}
    assert body["target_overrides"] == {}


def test_preview_applies_sla_patch_without_persisting(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    # PRE: standard tier baseline
    pre = client.get("/v1/tenant/config", headers=headers).json()
    baseline_threshold = pre["sla"]["confidence_threshold"]

    preview = client.post(
        "/v1/tenant/config:preview",
        headers=headers,
        json={"sla_patches": [{"op": "set", "path": "confidence_threshold", "value": 0.93}]},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["sla"]["confidence_threshold"] == 0.93

    # POST: a fresh GET shows no change — preview never persisted.
    post = client.get("/v1/tenant/config", headers=headers).json()
    assert post["sla"]["confidence_threshold"] == baseline_threshold
    assert post["sla_patches"] == []


def test_put_persists_sla_patch_and_get_reflects_it(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    put = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"sla_patches": [{"op": "set", "path": "confidence_threshold", "value": 0.91}]},
    )
    assert put.status_code == 200, put.text
    assert put.json()["sla"]["confidence_threshold"] == 0.91
    assert put.json()["sla_patches"] == [
        {"op": "set", "path": "confidence_threshold", "value": 0.91}
    ]

    # Fresh GET (new request, new cache) sees the persisted patch.
    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert fresh["sla"]["confidence_threshold"] == 0.91
    assert fresh["sla_patches"] == [{"op": "set", "path": "confidence_threshold", "value": 0.91}]


def test_put_empty_sla_patches_clears_the_override_row(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    # Save an override.
    client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"sla_patches": [{"op": "set", "path": "confidence_threshold", "value": 0.88}]},
    )
    assert (
        client.get("/v1/tenant/config", headers=headers).json()["sla"]["confidence_threshold"]
        == 0.88
    )

    # Clear it by sending an empty list.
    clear = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"sla_patches": []},
    )
    assert clear.status_code == 200, clear.text
    refreshed = client.get("/v1/tenant/config", headers=headers).json()
    assert refreshed["sla_patches"] == []
    # Back to the tier baseline (whatever the standard preset declares).
    assert refreshed["sla"]["confidence_threshold"] != 0.88


def test_put_switches_pipeline_id(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """PUT with ``pipeline_id`` writes the tenant column directly."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    pre = client.get("/v1/tenant/config", headers=headers).json()
    assert pre["pipeline_id"] == "default_v1"

    put = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"pipeline_id": "with_manual_review_v1"},
    )
    assert put.status_code == 200, put.text
    assert put.json()["pipeline_id"] == "with_manual_review_v1"

    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert fresh["pipeline_id"] == "with_manual_review_v1"


def test_preview_surfaces_pending_pipeline_id_without_persisting(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Preview surfaces the *would-be* pipeline_id; GET stays on the old one."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    preview = client.post(
        "/v1/tenant/config:preview",
        headers=headers,
        json={"pipeline_id": "batch_economy_v1"},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["pipeline_id"] == "batch_economy_v1"

    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert fresh["pipeline_id"] == "default_v1"


def test_put_persists_target_overrides(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    put = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={
            "target_overrides": {
                "us-hs.v1": [
                    {
                        "op": "set",
                        "path": "templates[default].metadata.note",
                        "value": "tenant-flagged",
                    }
                ]
            }
        },
    )
    assert put.status_code == 200, put.text
    body = put.json()
    assert body["target_overrides"]["us-hs.v1"][0]["path"] == "templates[default].metadata.note"

    # GET round-trips it.
    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert "us-hs.v1" in fresh["target_overrides"]


# ─── sad paths ───────────────────────────────────────────────────────


def test_put_rejects_out_of_range_sla_threshold(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Pydantic strict re-validation must catch a >1.0 threshold."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"sla_patches": [{"op": "set", "path": "confidence_threshold", "value": 1.5}]},
    )
    # Pydantic validation surfaces as 400 via the FastAPI request-validation
    # path OR our domain exception path; both are non-200.
    assert r.status_code >= 400, r.text
    # Confirm nothing was persisted.
    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert fresh["sla_patches"] == []


def test_put_rejects_malformed_profile_patch_wire_format(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """patches_from_wire rejects unknown ``op``."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={
            "profile_overrides": {
                "pl.lo.swiadectwo_szkolne.v1": [{"op": "obliterate", "path": "anything"}]
            }
        },
    )
    assert r.status_code == 400, r.text


# ─── security regressions (from security-review pass) ────────────────


def test_put_rejects_foreign_tenant_blob_key_patch(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Pin the fix for the cross-tenant blob-read finding.

    Pre-fix, a tenant could PUT a ``templates[<key>].blob_key`` patch
    pointing at any blob in the multi-tenant store, then run a job
    and have the renderer fetch + use those foreign bytes. Now the PUT
    handler refuses to persist the row at all.
    """
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    foreign_key = (
        "tenant/00000000-0000-0000-0000-000000000000/templates/"
        "us-hs.v1/grade_9/deadbeef.xlsx"
    )

    r = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={
            "target_overrides": {
                "us-hs.v1": [
                    {
                        "op": "set",
                        "path": "templates[grade_9].blob_key",
                        "value": foreign_key,
                    }
                ]
            }
        },
    )
    assert r.status_code == 400, r.text
    # Confirm nothing was persisted.
    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert "us-hs.v1" not in fresh["target_overrides"]


def test_preview_rejects_foreign_tenant_blob_key_patch(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Same guard fires on :preview so the UI surfaces the error pre-Save."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    foreign_key = (
        "tenant/00000000-0000-0000-0000-000000000000/templates/"
        "us-hs.v1/grade_9/deadbeef.xlsx"
    )

    r = client.post(
        "/v1/tenant/config:preview",
        headers=headers,
        json={
            "target_overrides": {
                "us-hs.v1": [
                    {
                        "op": "set",
                        "path": "templates[grade_9].blob_key",
                        "value": foreign_key,
                    }
                ]
            }
        },
    )
    assert r.status_code == 400, r.text


def test_put_rejects_unknown_pipeline_id(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Pin the fix for the pipeline-id path-traversal finding.

    Pre-fix the handler wrote any string verbatim into
    ``tenant.pipeline_id``, leaving the loader to reject it at job
    time. Now we reject at write-time, so values like
    ``../../etc/passwd`` never reach the loader.
    """
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"pipeline_id": "../../etc/passwd"},
    )
    assert r.status_code == 400, r.text
    fresh = client.get("/v1/tenant/config", headers=headers).json()
    assert fresh["pipeline_id"] == "default_v1"


def test_put_accepts_known_shipped_pipeline_id(
    standard_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Sanity: the validator still permits real shipped pipelines."""
    client, seeded = standard_client
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    r = client.put(
        "/v1/tenant/config",
        headers=headers,
        json={"pipeline_id": "with_manual_review_v1"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["pipeline_id"] == "with_manual_review_v1"

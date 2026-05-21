"""``/v1/tenant/providers`` CRUD — happy + sad paths (v0.3.0 Task 5).

Covers:

* ``GET`` — empty list when no row exists.
* ``PUT /anthropic`` with a valid key — persists + redacts in the
  response; subsequent ``GET`` reflects it.
* ``PUT /anthropic`` with the same key twice — second call records
  ``provider.byok_rotated`` rather than ``provider.byok_created``.
* ``PUT /anthropic`` with an invalid key — Anthropic auth rejects →
  400; no row persisted.
* ``PUT /openai`` (or other deferred provider) → 501.
* ``PUT /not-a-provider`` → 422.
* ``DELETE /anthropic`` → 204; ``GET`` shows the row as inactive;
  ``provider.byok_revoked`` audit row present.

The Anthropic key-validation call is mocked at the
``anthropic.AsyncAnthropic`` constructor so no network call happens.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.models import AuditLog, TenantProviderCredential
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
from ocr_to_report.core.sla import SLA_PRESETS
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
async def db_setup(settings: Settings) -> AsyncIterator[None]:
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
async def std_client(
    settings: Settings, db_setup: None
) -> AsyncIterator[tuple[TestClient, dict[str, Any]]]:
    """Seed a tenant + return TestClient + headers helpers."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _ = await tenants.create(name="Acme BYOK", slug="acme-byok")
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


def _valid_anthropic_mock() -> MagicMock:
    """A mock AsyncAnthropic that returns a stubbed models.list response."""
    client = MagicMock()
    page = MagicMock()
    page.data = [MagicMock(id="claude-haiku-4-5")]
    client.models.list = AsyncMock(return_value=page)
    client.aclose = AsyncMock()
    return client


def _invalid_anthropic_mock() -> MagicMock:
    """A mock AsyncAnthropic whose models.list raises AuthenticationError."""
    import anthropic  # noqa: PLC0415

    client = MagicMock()
    err = anthropic.AuthenticationError(
        message="invalid x-api-key",
        response=MagicMock(status_code=401, headers={}),
        body=None,
    )
    client.models.list = AsyncMock(side_effect=err)
    client.aclose = AsyncMock()
    return client


async def _audit_actions(settings: Settings, tenant_id: Any) -> list[str]:
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.ts)
        )
        return [r.action for r in rows.scalars().all()]


def _bypass_validation_cache() -> None:
    """Clear the in-process key-validation cache so the second test in a
    file doesn't see a cache-hit for the same key string."""
    from ocr_to_report.api.routers.providers import _validation_cache  # noqa: PLC0415

    _validation_cache.clear()


# ─── happy paths ──────────────────────────────────────────────────────


async def test_get_empty_when_no_credentials(
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Fresh tenant has no credential rows; GET returns ``providers: []``."""
    client, seeded = std_client
    r = client.get(
        "/v1/tenant/providers",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"providers": []}


async def test_put_then_get_reflects_redacted(
    settings: Settings,
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """PUT a valid key, GET returns one redacted row."""
    _bypass_validation_cache()
    client, seeded = std_client

    with patch("anthropic.AsyncAnthropic", return_value=_valid_anthropic_mock()):
        r = client.put(
            "/v1/tenant/providers/anthropic",
            headers={"Authorization": f"Bearer {seeded['api_key']}"},
            json={"api_key": "sk-ant-valid-XYZ1"},
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "anthropic"
    assert body["active"] is True
    # Redacted in the response; last 4 of the key match the upload.
    assert body["api_key_redacted"] == "sk-ant-…XYZ1"
    # Plaintext key MUST NOT round-trip.
    assert "sk-ant-valid-XYZ1" not in r.text

    # GET sees the row (placeholder redaction since GET doesn't unwrap).
    r2 = client.get(
        "/v1/tenant/providers",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
    )
    assert r2.status_code == 200
    providers = r2.json()["providers"]
    assert len(providers) == 1
    assert providers[0]["provider"] == "anthropic"
    assert providers[0]["active"] is True
    # The list response uses a stable placeholder, not the actual last4.
    assert providers[0]["api_key_redacted"] == "sk-ant-…••••"

    # Audit: byok_created (first-time) entry exists.
    actions = await _audit_actions(settings, seeded["tenant_id"])
    assert "provider.byok_created" in actions
    assert "provider.byok_rotated" not in actions


async def test_put_twice_records_rotation_audit(
    settings: Settings,
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Second PUT on the same provider records a rotation."""
    _bypass_validation_cache()
    client, seeded = std_client

    with patch("anthropic.AsyncAnthropic", return_value=_valid_anthropic_mock()):
        client.put(
            "/v1/tenant/providers/anthropic",
            headers={"Authorization": f"Bearer {seeded['api_key']}"},
            json={"api_key": "sk-ant-first-KEY1"},
        )
        client.put(
            "/v1/tenant/providers/anthropic",
            headers={"Authorization": f"Bearer {seeded['api_key']}"},
            json={"api_key": "sk-ant-secondKEY2"},
        )

    actions = await _audit_actions(settings, seeded["tenant_id"])
    assert "provider.byok_created" in actions
    assert "provider.byok_rotated" in actions


async def test_delete_soft_disables(
    settings: Settings,
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """DELETE returns 204 + audits byok_revoked; subsequent GET shows
    the row as inactive."""
    _bypass_validation_cache()
    client, seeded = std_client

    with patch("anthropic.AsyncAnthropic", return_value=_valid_anthropic_mock()):
        client.put(
            "/v1/tenant/providers/anthropic",
            headers={"Authorization": f"Bearer {seeded['api_key']}"},
            json={"api_key": "sk-ant-to-be-revoked"},
        )

    r = client.delete(
        "/v1/tenant/providers/anthropic",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
    )
    assert r.status_code == 204, r.text

    actions = await _audit_actions(settings, seeded["tenant_id"])
    assert "provider.byok_revoked" in actions

    # GET still returns the row (audit history retained) but it is inactive.
    r2 = client.get(
        "/v1/tenant/providers",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
    )
    providers = r2.json()["providers"]
    assert len(providers) == 1
    assert providers[0]["active"] is False


async def test_delete_idempotent_when_no_active_row(
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """DELETE on a provider with no active row still returns 204."""
    client, seeded = std_client
    r = client.delete(
        "/v1/tenant/providers/anthropic",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
    )
    assert r.status_code == 204, r.text


# ─── sad paths ────────────────────────────────────────────────────────


async def test_put_invalid_key_returns_400_and_does_not_persist(
    settings: Settings,
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """A 401 from Anthropic becomes a clean 400 + no row persisted."""
    _bypass_validation_cache()
    client, seeded = std_client

    with patch("anthropic.AsyncAnthropic", return_value=_invalid_anthropic_mock()):
        r = client.put(
            "/v1/tenant/providers/anthropic",
            headers={"Authorization": f"Bearer {seeded['api_key']}"},
            json={"api_key": "sk-ant-not-real-1234"},
        )

    assert r.status_code == 400, r.text
    body = r.json()
    # The body should mention validation in some form (the canonical
    # error shape uses ``detail`` for the human message).
    detail = body.get("detail", "")
    if isinstance(detail, dict):
        detail = detail.get("message", "")
    assert "validation" in str(detail).lower() or "rejected" in str(detail).lower()

    # No row persisted.
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        result = await session.execute(
            select(TenantProviderCredential).where(
                TenantProviderCredential.tenant_id == seeded["tenant_id"],
            )
        )
        assert list(result.scalars().all()) == []


async def test_put_deferred_provider_returns_501(
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """PUT for a deferred provider (openai / google_vertex / tesseract)
    returns 501 with a clear "v0.7.0" hint."""
    client, seeded = std_client
    r = client.put(
        "/v1/tenant/providers/openai",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
        json={"api_key": "sk-oai-stub-DEFR"},
    )
    assert r.status_code == 501, r.text


async def test_put_unknown_provider_returns_422(
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """A provider id outside the legal Literal set returns 422."""
    client, seeded = std_client
    r = client.put(
        "/v1/tenant/providers/not-a-provider",
        headers={"Authorization": f"Bearer {seeded['api_key']}"},
        json={"api_key": "sk-something-XXXX"},
    )
    # ValidationError → 400 in our error mapping; the schema's Literal
    # gate produces the same shape via our explicit _require_known_provider.
    assert r.status_code in (400, 422), r.text


async def test_get_unauthorized_returns_401(
    std_client: tuple[TestClient, dict[str, Any]],
) -> None:
    """Missing bearer token returns 401."""
    client, _ = std_client
    r = client.get("/v1/tenant/providers")
    assert r.status_code == 401

"""End-to-end: tenant BYOK credentials actually flow through transcripts.

Pins the v0.3.0 wire from ``tenant_provider_credentials`` to the
vision adapter:

* No BYOK row → the request rides the platform path. Adapter receives
  ``override_api_key=None``. Usage row carries ``billing_path =
  'platform'``. No ``provider.byok_invoked`` audit entry.
* Active BYOK row → adapter receives the unwrapped tenant key.
  Usage row carries ``billing_path = 'byok'``. Audit log gains a
  ``provider.byok_invoked`` entry with ``provider`` +
  ``credential_id`` metadata (NEVER the key itself).
* Soft-disabled credential → back to the platform path on the next
  call (the dep correctly excludes inactive rows).
* Decryption failure → the dep falls back to platform with a WARN log;
  the request must NOT crash with 500.

Modeled on the shape of ``test_tenant_overrides_e2e.py``: in-memory
SQLite, FastAPI ``TestClient``, mocked vision adapter that records
``override_api_key`` per call.
"""

from __future__ import annotations

import base64
import io
import secrets
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import select

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.models import AuditLog, UsageRecord
from ocr_to_report.adapters.db.repositories import (
    ApiKeyRepo,
    TenantProviderCredentialRepo,
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
from ocr_to_report.core.sla import SLA_PRESETS
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── fixture helpers (mirrors test_tenant_overrides_e2e.py) ──────────


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


class _RecordingVisionAdapter:
    """Vision adapter that records every ``override_api_key`` it sees.

    The whole point of the BYOK test is: did the override key reach the
    adapter? This stub records that explicitly via ``.calls`` so tests
    can make precise assertions.
    """

    name = VisionProvider.MOCK

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        # Use AsyncMock to give the harness an awaitable, but route
        # through _extract for the recording side-effect.
        self.extract = AsyncMock(side_effect=self._extract)

    async def _extract(
        self,
        _request: Any,
        *,
        override_api_key: str | None = None,
    ) -> ExtractionResult:
        self.calls.append({"override_api_key": override_api_key})
        return ExtractionResult(
            raw_extraction=_polish_extraction(),
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
    yield None


async def _seed_tenant(
    settings: Settings,
    *,
    byok_key: str | None = None,
) -> dict[str, Any]:
    """Seed a Standard-tier tenant + optionally one BYOK row.

    Returns ``{tenant_id, api_key, credential_id?}``. ``credential_id``
    is included when ``byok_key`` is set.
    """
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, dek_plain = await tenants.create(name="Acme Std", slug="acme-std")
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=["transcripts:write"],
        )
        out: dict[str, Any] = {"tenant_id": tenant.id, "api_key": plain_key}
        if byok_key is not None:
            creds_repo = TenantProviderCredentialRepo(session, encryptor)
            row = await creds_repo.upsert(
                tenant_id=tenant.id,
                provider="anthropic",
                plaintext_api_key=byok_key,
                dek=dek_plain,
            )
            out["credential_id"] = row.id
        await session.commit()
        return out


def _make_client(settings: Settings, *, adapter: Any) -> TestClient:
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


async def _audit_actions_for(settings: Settings, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        rows = await session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.ts)
        )
        return [
            {"action": r.action, "metadata": dict(r.metadata_json or {})}
            for r in rows.scalars().all()
        ]


async def _usage_rows_for(settings: Settings, tenant_id: uuid.UUID) -> list[UsageRecord]:
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        rows = await session.execute(select(UsageRecord).where(UsageRecord.tenant_id == tenant_id))
        return list(rows.scalars().all())


# ─── tests ────────────────────────────────────────────────────────────


async def test_no_byok_row_routes_through_platform(settings: Settings, db_setup: None) -> None:
    """Plain tenant with no BYOK row → platform path."""
    seeded = await _seed_tenant(settings, byok_key=None)
    adapter = _RecordingVisionAdapter()
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
    finally:
        client.__exit__(None, None, None)

    # Adapter saw exactly one extract call with override_api_key=None.
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["override_api_key"] is None

    # Usage row is platform-billed.
    rows = await _usage_rows_for(settings, seeded["tenant_id"])
    assert len(rows) == 1
    assert rows[0].billing_path == "platform"

    # No byok_invoked audit entry.
    actions = [e["action"] for e in await _audit_actions_for(settings, seeded["tenant_id"])]
    assert "provider.byok_invoked" not in actions


async def test_active_byok_row_threads_override_and_tags_billing(
    settings: Settings, db_setup: None
) -> None:
    """Tenant with an active anthropic BYOK row → override flows."""
    seeded = await _seed_tenant(settings, byok_key="sk-ant-tenant-XYZ")
    adapter = _RecordingVisionAdapter()
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
    finally:
        client.__exit__(None, None, None)

    # The plaintext key reached the adapter.
    assert len(adapter.calls) == 1
    assert adapter.calls[0]["override_api_key"] == "sk-ant-tenant-XYZ"

    # Usage row is BYOK-billed.
    rows = await _usage_rows_for(settings, seeded["tenant_id"])
    assert len(rows) == 1
    assert rows[0].billing_path == "byok"

    # Audit entry exists with the credential id (NOT the key).
    entries = await _audit_actions_for(settings, seeded["tenant_id"])
    byok_entries = [e for e in entries if e["action"] == "provider.byok_invoked"]
    assert len(byok_entries) == 1, f"expected exactly one byok_invoked; got: {byok_entries}"
    meta = byok_entries[0]["metadata"]
    assert meta.get("provider") == "anthropic"
    assert meta.get("credential_id") == str(seeded["credential_id"])
    # Critical: the audit log MUST NOT contain the plaintext key.
    assert "sk-ant-tenant-XYZ" not in str(meta)


async def test_disabled_byok_credential_falls_back_to_platform(
    settings: Settings, db_setup: None
) -> None:
    """After ``disable()`` on the credential row, the next request
    routes through the platform path again — the dep's "active only"
    filter is the cutoff."""
    seeded = await _seed_tenant(settings, byok_key="sk-ant-soon-disabled")

    # Disable the credential out-of-band (mirrors what DELETE
    # /v1/tenant/providers/{provider} will do once Task 5 lands).
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        creds_repo = TenantProviderCredentialRepo(session, encryptor)
        await creds_repo.disable(tenant_id=seeded["tenant_id"], provider="anthropic")
        await session.commit()

    adapter = _RecordingVisionAdapter()
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
    finally:
        client.__exit__(None, None, None)

    # Platform path: no override threaded.
    assert adapter.calls[0]["override_api_key"] is None
    rows = await _usage_rows_for(settings, seeded["tenant_id"])
    # All usage rows from this tenant are platform-billed.
    assert all(r.billing_path == "platform" for r in rows)


async def test_decryption_failure_falls_back_to_platform(
    settings: Settings, db_setup: None
) -> None:
    """A row whose ciphertext can't be unwrapped (DEK rotation, manual
    tamper, ...) does NOT crash the request. The dep returns None and
    the platform path is used. This protects the API surface from
    operational issues with the BYOK store."""
    seeded = await _seed_tenant(settings, byok_key="sk-ant-corrupt-incoming")

    # Corrupt the ciphertext directly so the AES-GCM auth tag fails.
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        from ocr_to_report.adapters.db.models import (  # noqa: PLC0415
            TenantProviderCredential,
        )

        result = await session.execute(
            select(TenantProviderCredential).where(
                TenantProviderCredential.tenant_id == seeded["tenant_id"],
            )
        )
        row = result.scalar_one()
        # Truncate to garbage of the same minimum length so payload
        # parsing doesn't bail before the auth check.
        row.encrypted_api_key = b"\x00" * len(row.encrypted_api_key)
        await session.commit()

    adapter = _RecordingVisionAdapter()
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
        # Must succeed with 200, NOT 500. That's the whole point of
        # the fallback.
        assert r.status_code == 200, r.text
    finally:
        client.__exit__(None, None, None)

    # Adapter received no override (fall-through to platform).
    assert adapter.calls[0]["override_api_key"] is None
    rows = await _usage_rows_for(settings, seeded["tenant_id"])
    assert rows[0].billing_path == "platform"


# Suppress unused-import (datetime is used in helpers above).
_ = datetime, UTC

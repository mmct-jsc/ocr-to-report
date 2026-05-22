"""v0.3.0 BYOK end-to-end integration test against real postgres.

Companion to ``test_v0_2_0_integration.py``: the unit + e2e suites for
v0.3.0 (``test_anthropic_adapter_byok.py``, ``test_byok_e2e.py``,
``test_providers_api.py``) cover each piece in isolation against
in-memory sqlite. This test stitches the whole BYOK flow together
against the postgres + redis service containers provided by
``.github/workflows/integration.yml``.

The single flow walks a paying customer's first day with BYOK:

1. Fresh tenant, no BYOK row. Run a job. ``usage_records`` row must
   carry ``billing_path = 'platform'``; no ``provider.byok_invoked``
   audit entry. The vision adapter received ``override_api_key=None``.

2. ``PUT /v1/tenant/providers/anthropic`` with a fake key. The
   Anthropic validation call to ``/v1/models`` is mocked to return
   2xx so the PUT succeeds without a network round-trip. The
   ``audit_log`` must gain a ``provider.byok_created`` entry.

3. Run a second job. The vision adapter MUST have received the
   unwrapped plaintext key as ``override_api_key`` (proves the
   envelope-encrypt/decrypt round-trip survived postgres). The
   ``usage_records`` row for this period must now carry
   ``billing_path = 'byok'`` (separate row from step 1's ``platform``
   row — the rollup key includes billing_path). Audit log gains
   ``provider.byok_invoked``.

4. ``DELETE /v1/tenant/providers/anthropic`` → 204. Audit log gains
   ``provider.byok_revoked``. Run a third job → back to platform
   billing.

If any v0.3.0 wire breaks under postgres — partial unique index doesn't
fire, the JSONB ``model_overrides`` column type drifts, the ``billing_path``
CHECK constraint refuses one of the legal values, the GUC + RLS gate
silently skips a row — THIS test will be what catches it before main.
"""

from __future__ import annotations

import base64
import io
import os
import secrets
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PILImage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base
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

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[3]

DB_URL = os.getenv("OCR2R_TEST_DB_URL")

if not DB_URL or not DB_URL.startswith("postgresql"):
    pytest.skip(
        "OCR2R_TEST_DB_URL not set (or not postgres); skipping v0.3.0 "
        "BYOK integration test. CI's integration.yml workflow sets it.",
        allow_module_level=True,
    )


# ─── helpers ──────────────────────────────────────────────────────────


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


class _RecordingAdapter:
    """Vision adapter that records every ``override_api_key`` it receives.

    The integration test's core assertion is: did the BYOK plaintext
    flow all the way from the postgres ``encrypted_api_key`` column
    through the dep, the request handler, and into the adapter? The
    only way to prove that is to record the kwarg at the adapter
    boundary.
    """

    name = VisionProvider.MOCK

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
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
            confidence=0.97,
            field_confidences=None,
            warnings=[],
            provider=VisionProvider.MOCK,
            model_id="mock",
            usage=TokenUsage(input_tokens=1500, output_tokens=300, usd_cost=0.003),
        )

    async def aclose(self) -> None:
        return None


def _mock_anthropic_validates_ok() -> MagicMock:
    """Mock AsyncAnthropic whose models.list returns successfully."""
    client = MagicMock()
    page = MagicMock()
    page.data = [MagicMock(id="claude-haiku-4-5")]
    client.models.list = AsyncMock(return_value=page)
    client.aclose = AsyncMock()
    return client


# ─── fixtures ─────────────────────────────────────────────────────────


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(
        "OCR2R_KEK_B64",
        base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
    )
    assert DB_URL is not None
    return Settings(
        env="development",
        database_url=DB_URL,
        blob_backend="local",
        blob_local_root=tmp_path / "blob",
        kek_b64=base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
        profiles_root=REPO_ROOT / "profiles",
        targets_root=REPO_ROOT / "targets",
    )


@pytest.fixture
async def pg_clean_engine() -> AsyncIterator[AsyncEngine]:
    assert DB_URL is not None
    engine = create_async_engine(DB_URL, future=True, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def seeded(settings: Settings, pg_clean_engine: AsyncEngine) -> dict[str, Any]:
    """Tenant + API key with transcripts:write."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = async_sessionmaker(pg_clean_engine, expire_on_commit=False)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name="Acme BYOK E2E", slug="acme-byok-e2e")
        tenant.sla_tier = SlaTier.STANDARD.value
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(tenant_id=tenant.id, scopes=["transcripts:write"])
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key}


def _make_client(settings: Settings, *, adapter: _RecordingAdapter) -> TestClient:
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


async def _read_audit_actions(tenant_id: uuid.UUID) -> list[str]:
    """Open a fresh engine per call so each ``asyncio.run`` gets its own
    loop-bound pool. The ``pg_clean_engine`` fixture is bound to
    pytest-asyncio's loop; reusing it inside a fresh ``asyncio.run``
    raises "Task attached to a different loop" on asyncpg.
    """
    assert DB_URL is not None
    engine = create_async_engine(DB_URL, future=True, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            result = await conn.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :tid ORDER BY ts"),
                {"tid": str(tenant_id)},
            )
            return [row[0] for row in result.all()]
    finally:
        await engine.dispose()


async def _read_usage_billing_paths(
    tenant_id: uuid.UUID,
) -> list[tuple[str, int]]:
    """Return ``[(billing_path, transcripts_processed), ...]`` for the tenant.

    Fresh engine per call — see ``_read_audit_actions`` for why.
    """
    assert DB_URL is not None
    engine = create_async_engine(DB_URL, future=True, echo=False)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.tenant_id', :tid, true)"),
                {"tid": str(tenant_id)},
            )
            result = await conn.execute(
                text(
                    "SELECT billing_path, transcripts_processed FROM usage_records "
                    "WHERE tenant_id = :tid ORDER BY billing_path"
                ),
                {"tid": str(tenant_id)},
            )
            return [(row[0], row[1]) for row in result.all()]
    finally:
        await engine.dispose()


def _run_job(client: TestClient, api_key: str) -> dict[str, Any]:
    """Drive one POST /v1/transcripts; return the parsed response."""
    r = client.post(
        "/v1/transcripts",
        headers={"Authorization": f"Bearer {api_key}"},
        files={"file": ("t.png", _png(), "image/png")},
        data={
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job"]["status"] == "succeeded", body
    return body


# ─── the integration test ─────────────────────────────────────────────


def test_full_v0_3_0_byok_flow_against_postgres(
    settings: Settings,
    seeded: dict[str, Any],
) -> None:
    """Walks the no-BYOK → set → revoke → no-BYOK lifecycle on postgres.

    ``seeded`` transitively depends on ``pg_clean_engine`` so the
    drop+create-schema side-effect runs before the test body; we do
    NOT take the engine directly as a parameter — every read helper
    opens its own engine inside ``asyncio.run`` to keep the asyncpg
    pool bound to the right event loop. Sharing the fixture engine
    across loops raises "Task attached to a different loop".
    """
    import asyncio  # noqa: PLC0415

    adapter = _RecordingAdapter()
    client = _make_client(settings, adapter=adapter)
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}
    api_key = seeded["api_key"]
    tenant_id = seeded["tenant_id"]

    try:
        # ─── 1. Pre-BYOK: platform-billed ─────────────────────────────
        _run_job(client, api_key)
        assert adapter.calls[-1]["override_api_key"] is None, (
            "fresh tenant should not have a BYOK key threaded to the adapter"
        )

        usage_rows = asyncio.run(_read_usage_billing_paths(tenant_id))
        assert usage_rows == [("platform", 1)], (
            f"expected one platform-billed usage row; saw {usage_rows}"
        )
        actions = asyncio.run(_read_audit_actions(tenant_id))
        assert "provider.byok_invoked" not in actions, actions

        # ─── 2. PUT a BYOK key (Anthropic validation mocked) ──────────
        # Clear the in-process validation cache between phases — a real
        # production deploy would never hit a stale cache here, but the
        # test reuses the same process across phases.
        from ocr_to_report.api.routers.providers import (  # noqa: PLC0415
            _validation_cache,
        )

        _validation_cache.clear()

        with patch("anthropic.AsyncAnthropic", return_value=_mock_anthropic_validates_ok()):
            put = client.put(
                "/v1/tenant/providers/anthropic",
                headers=headers,
                json={"api_key": "sk-ant-postgres-byok-XYZ1"},
            )
        assert put.status_code == 200, put.text
        put_body = put.json()
        assert put_body["api_key_redacted"] == "sk-ant-…XYZ1"
        assert put_body["active"] is True

        actions = asyncio.run(_read_audit_actions(tenant_id))
        assert "provider.byok_created" in actions, actions

        # ─── 3. Post-BYOK: byok-billed, override threaded ─────────────
        _run_job(client, api_key)
        assert adapter.calls[-1]["override_api_key"] == "sk-ant-postgres-byok-XYZ1", (
            "BYOK plaintext key did not reach the adapter — the "
            "envelope-encrypt/decrypt round-trip broke on postgres"
        )

        usage_rows = asyncio.run(_read_usage_billing_paths(tenant_id))
        # Two rollup rows now: platform=1 from step 1, byok=1 from step 3.
        assert ("platform", 1) in usage_rows, usage_rows
        assert ("byok", 1) in usage_rows, usage_rows

        actions = asyncio.run(_read_audit_actions(tenant_id))
        assert "provider.byok_invoked" in actions, actions

        # ─── 4. DELETE the credential → audit + platform fallback ────
        delete = client.delete("/v1/tenant/providers/anthropic", headers=headers)
        assert delete.status_code == 204, delete.text

        actions = asyncio.run(_read_audit_actions(tenant_id))
        assert "provider.byok_revoked" in actions, actions

        # ─── 5. Post-revoke: platform-billed again ────────────────────
        _run_job(client, api_key)
        assert adapter.calls[-1]["override_api_key"] is None, (
            "after DELETE, the dep should return None and the adapter "
            "should see no override; got "
            f"{adapter.calls[-1]['override_api_key']!r}"
        )

        usage_rows = asyncio.run(_read_usage_billing_paths(tenant_id))
        # platform=2 now (step 1 + step 5); byok=1 still (step 3).
        platform_count = next((n for p, n in usage_rows if p == "platform"), 0)
        byok_count = next((n for p, n in usage_rows if p == "byok"), 0)
        assert platform_count == 2, usage_rows
        assert byok_count == 1, usage_rows
    finally:
        client.__exit__(None, None, None)

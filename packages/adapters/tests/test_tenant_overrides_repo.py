"""``TenantOverrideRepo`` — per-tenant JSON-patch storage.

The ``tenant_overrides`` table holds one row per ``(tenant_id, scope,
target_id)`` triple. Patches are a JSON array of ``{op, path, value}``
documents matching ``core.overrides.resolver.OverridePatch``. The repo
exposes the minimum surface the API layer needs:

* ``upsert`` — create or update the row at the given key, optionally
  toggling the ``enabled`` flag.
* ``list_for_tenant`` — every enabled override for a tenant, used at
  request time by the resolver wiring (Task 4).
* ``delete`` — remove a row (or hard-disable it).
"""

from __future__ import annotations

import base64
import secrets
import uuid
from collections.abc import AsyncIterator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base
from ocr_to_report.adapters.db.repositories import TenantOverrideRepo, TenantRepo


@pytest.fixture
def kek_env(monkeypatch: pytest.MonkeyPatch) -> str:
    kek = base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode()
    monkeypatch.setenv("OCR2R_KEK_B64", kek)
    return kek


@pytest.fixture
def encryptor(kek_env: str) -> EnvelopeEncryptor:
    return EnvelopeEncryptor(EnvKEKProvider())


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    async with sm() as s:
        try:
            yield s
            await s.commit()
        finally:
            await s.close()
    await engine.dispose()


@pytest.fixture
async def tenant_id(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> uuid.UUID:
    tenants = TenantRepo(session, encryptor)
    tenant, _ = await tenants.create(name="Acme", slug="acme")
    return tenant.id


@pytest.mark.asyncio
async def test_upsert_creates_new_row(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    row = await repo.upsert(
        tenant_id=tenant_id,
        scope="sla",
        target_id=None,
        patches=[{"op": "set", "path": "confidence_threshold", "value": 0.95}],
    )
    assert row.id is not None
    assert row.scope == "sla"
    assert row.target_id is None
    assert row.patches == [
        {"op": "set", "path": "confidence_threshold", "value": 0.95}
    ]
    assert row.enabled is True


@pytest.mark.asyncio
async def test_upsert_updates_existing_row_for_same_key(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    first = await repo.upsert(
        tenant_id=tenant_id,
        scope="sla",
        target_id=None,
        patches=[{"op": "set", "path": "confidence_threshold", "value": 0.90}],
    )
    second = await repo.upsert(
        tenant_id=tenant_id,
        scope="sla",
        target_id=None,
        patches=[{"op": "set", "path": "confidence_threshold", "value": 0.95}],
    )
    # Same row identity; payload swapped.
    assert second.id == first.id
    assert second.patches[0]["value"] == 0.95


@pytest.mark.asyncio
async def test_upsert_creates_separate_rows_for_different_target_ids(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    """The ``(tenant, scope, target_id)`` triple is the unique key.
    Two ``scope=template`` rows for different targets must coexist."""
    repo = TenantOverrideRepo(session)
    a = await repo.upsert(
        tenant_id=tenant_id,
        scope="template",
        target_id="us-hs.v1",
        patches=[{"op": "set", "path": "templates[grade_9].blob_key", "value": "a"}],
    )
    b = await repo.upsert(
        tenant_id=tenant_id,
        scope="template",
        target_id="uk-ucas.v1",
        patches=[{"op": "set", "path": "templates[ucas_form].blob_key", "value": "b"}],
    )
    assert a.id != b.id


@pytest.mark.asyncio
async def test_list_for_tenant_returns_only_enabled_rows(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    await repo.upsert(
        tenant_id=tenant_id, scope="sla", target_id=None, patches=[{"op": "set", "path": "x", "value": 1}],
    )
    await repo.upsert(
        tenant_id=tenant_id, scope="pipeline", target_id=None, patches=[{"op": "set", "path": "y", "value": 2}],
        enabled=False,
    )
    rows = await repo.list_for_tenant(tenant_id)
    scopes = {r.scope for r in rows}
    assert scopes == {"sla"}, f"expected only enabled rows, got {scopes}"


@pytest.mark.asyncio
async def test_list_for_tenant_filters_by_scope(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    await repo.upsert(
        tenant_id=tenant_id, scope="sla", target_id=None, patches=[{"op": "set", "path": "x", "value": 1}],
    )
    await repo.upsert(
        tenant_id=tenant_id, scope="template", target_id="us-hs.v1",
        patches=[{"op": "set", "path": "y", "value": 2}],
    )
    only_sla = await repo.list_for_tenant(tenant_id, scope="sla")
    assert len(only_sla) == 1
    assert only_sla[0].scope == "sla"


@pytest.mark.asyncio
async def test_delete_removes_row(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    row = await repo.upsert(
        tenant_id=tenant_id, scope="sla", target_id=None, patches=[{"op": "set", "path": "x", "value": 1}],
    )
    deleted = await repo.delete(tenant_id=tenant_id, scope="sla", target_id=None)
    assert deleted is True
    rows = await repo.list_for_tenant(tenant_id)
    assert all(r.id != row.id for r in rows)


@pytest.mark.asyncio
async def test_delete_missing_returns_false(
    session: AsyncSession, tenant_id: uuid.UUID
) -> None:
    repo = TenantOverrideRepo(session)
    deleted = await repo.delete(tenant_id=tenant_id, scope="sla", target_id=None)
    assert deleted is False

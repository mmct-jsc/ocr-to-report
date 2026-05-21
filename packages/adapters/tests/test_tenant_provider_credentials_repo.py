"""``TenantProviderCredentialRepo`` — per-tenant BYOK credential store.

Pins the contract that the v0.3.0 BYOK path leans on:

* ``upsert(tenant_id, provider, plaintext_api_key)`` encrypts with the
  tenant DEK, writes the row, and marks any prior active row inactive
  in the SAME flush. The end-state is exactly one active row per
  ``(tenant, provider)``, with the previous (now inactive) row carrying
  ``rotated_at`` so the audit trail survives.
* ``get_active_for_tenant(tenant_id, provider)`` returns a
  :class:`TenantCredential` view with the UNWRAPPED plaintext key. None
  when there is no active row.
* Soft-disable (``active=False``) excludes the row from
  ``get_active_for_tenant`` — that's the DELETE-on-API path.
* Rotation history accumulates: querying ``list_for_tenant`` returns
  every row (active + inactive) — the UI uses this to render the
  "last rotated at" affordance.

These tests run on SQLite (in-memory) — fast unit feedback. The
postgres-only partial-index invariant is pinned in
``test_v0_3_0_migrations.py``.
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
from ocr_to_report.adapters.db.repositories import (
    TenantProviderCredentialRepo,
    TenantRepo,
)


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
async def tenant_pair(
    session: AsyncSession, encryptor: EnvelopeEncryptor
) -> tuple[uuid.UUID, bytes]:
    """Return ``(tenant_id, plaintext_dek)`` for tests that need to
    encrypt / decrypt themselves."""
    tenants = TenantRepo(session, encryptor)
    tenant, dek_plain = await tenants.create(name="Acme", slug="acme")
    return tenant.id, dek_plain


@pytest.mark.asyncio
async def test_upsert_creates_new_row_with_encrypted_key(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """Fresh upsert encrypts + persists; round-trip recovers plaintext."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)

    row = await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-test-12345678",
        dek=dek_plain,
    )

    assert row.id is not None
    assert row.tenant_id == tenant_id
    assert row.provider == "anthropic"
    assert row.active is True
    # Crypto is real — the ciphertext blob is NOT the plaintext.
    assert b"sk-ant" not in row.encrypted_api_key
    # And it round-trips.
    plain = await repo.unwrap_key(row, dek_plain)
    assert plain == "sk-ant-test-12345678"


@pytest.mark.asyncio
async def test_get_active_for_tenant_returns_unwrapped_view(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """The read-side helper unwraps the key in one step."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)
    await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-ABCD",
        dek=dek_plain,
    )

    creds = await repo.get_active_for_tenant(tenant_id, provider="anthropic", dek=dek_plain)
    assert creds is not None
    assert creds.provider == "anthropic"
    assert creds.api_key == "sk-ant-ABCD"
    assert creds.active is True


@pytest.mark.asyncio
async def test_get_active_returns_none_when_no_row(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """No BYOK row → ``None``. The transcripts handler treats this as
    "platform-billed" — never raises."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)
    assert await repo.get_active_for_tenant(tenant_id, provider="anthropic", dek=dek_plain) is None


@pytest.mark.asyncio
async def test_rotation_marks_previous_active_inactive_with_rotated_at(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """Calling ``upsert`` twice for the same ``(tenant, provider)`` is a
    rotation: the previous row goes inactive with ``rotated_at`` set;
    the new row is the only active one."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)

    first = await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-first",
        dek=dek_plain,
    )
    first_id = first.id

    second = await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-second",
        dek=dek_plain,
    )

    # Refresh from DB to see the in-flush mutations.
    await session.refresh(first)
    assert first.active is False
    assert first.rotated_at is not None
    assert second.id != first_id
    assert second.active is True

    # Only the new key is exposed to consumers.
    creds = await repo.get_active_for_tenant(tenant_id, provider="anthropic", dek=dek_plain)
    assert creds is not None
    assert creds.api_key == "sk-ant-second"


@pytest.mark.asyncio
async def test_disable_excludes_row_from_get_active(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """``disable`` flips ``active=False`` and persists the row for audit.
    ``get_active_for_tenant`` returns ``None`` after."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)
    await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-disable-me",
        dek=dek_plain,
    )

    disabled = await repo.disable(tenant_id=tenant_id, provider="anthropic")
    assert disabled is True

    assert await repo.get_active_for_tenant(tenant_id, provider="anthropic", dek=dek_plain) is None

    # And the row still exists (soft-delete, not hard).
    all_rows = await repo.list_for_tenant(tenant_id)
    assert len(all_rows) == 1
    assert all_rows[0].active is False


@pytest.mark.asyncio
async def test_disable_no_op_when_no_active_row(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """Disabling when there's no active row returns ``False`` and never
    raises — idempotent."""
    tenant_id, _ = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)
    assert await repo.disable(tenant_id=tenant_id, provider="anthropic") is False


@pytest.mark.asyncio
async def test_different_providers_are_independent(
    session: AsyncSession,
    encryptor: EnvelopeEncryptor,
    tenant_pair: tuple[uuid.UUID, bytes],
) -> None:
    """Upserting for one provider does not touch others — the
    rotation logic keys on ``(tenant, provider)`` together."""
    tenant_id, dek_plain = tenant_pair
    repo = TenantProviderCredentialRepo(session, encryptor)
    await repo.upsert(
        tenant_id=tenant_id,
        provider="anthropic",
        plaintext_api_key="sk-ant-keep",
        dek=dek_plain,
    )
    # v0.3.0 only routes anthropic, but the table accepts the others —
    # this guards future rollouts.
    await repo.upsert(
        tenant_id=tenant_id,
        provider="openai",
        plaintext_api_key="sk-oai-also",
        dek=dek_plain,
    )

    anthropic = await repo.get_active_for_tenant(tenant_id, provider="anthropic", dek=dek_plain)
    openai = await repo.get_active_for_tenant(tenant_id, provider="openai", dek=dek_plain)
    assert anthropic is not None and anthropic.api_key == "sk-ant-keep"
    assert openai is not None and openai.api_key == "sk-oai-also"

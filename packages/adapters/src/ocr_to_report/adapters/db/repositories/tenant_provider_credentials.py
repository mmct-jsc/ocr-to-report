"""``TenantProviderCredentialRepo`` — per-tenant BYOK credential storage.

Holds Anthropic / provider API keys encrypted with the tenant's DEK
(same envelope-crypto pattern as :class:`WebhookRepo`). The plan
(``docs/plans/2026-05-21-v0.3.0-byok-design.md``) calls out the three
invariants pinned here:

1. ``upsert`` is also the rotation primitive — a second call for the
   same ``(tenant, provider)`` flips the previous active row to
   ``active=False, rotated_at=now()`` in the same flush as the insert.
   The end-state is exactly one active row.
2. ``get_active_for_tenant`` returns the unwrapped plaintext as a
   :class:`TenantCredential` view; never the ORM row directly. None
   when there is no active row → caller treats it as platform-billed.
3. ``disable`` is the API DELETE path — soft-disable (``active=False``)
   preserves the row for audit. Hard delete is intentionally not
   exposed.

The postgres-only partial unique index
(``ix_tenant_provider_credentials_active``) enforces (1) at the DB
layer; the in-flush logic here enforces it on SQLite (and as
defense-in-depth on postgres).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import TenantProviderCredential

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ocr_to_report.adapters.crypto import EnvelopeEncryptor


@dataclass(frozen=True, slots=True)
class TenantCredential:
    """The unwrapped, request-time view of a BYOK row.

    Carries the plaintext ``api_key`` only — callers never inspect the
    underlying ORM row directly. Includes the credential id so the audit
    log can record which credential a request used without echoing the
    key.
    """

    id: uuid.UUID
    tenant_id: uuid.UUID
    provider: str
    api_key: str
    active: bool
    region: str | None
    rotated_at: datetime | None


class TenantProviderCredentialRepo:
    """Repository for the ``tenant_provider_credentials`` table.

    The repo binds the encryptor at construction time but takes the
    tenant DEK explicitly on every read/write — the DEK lives only in
    the request scope, never on the repo.
    """

    def __init__(
        self,
        session: AsyncSession,
        encryptor: EnvelopeEncryptor,
    ) -> None:
        self._session = session
        self._encryptor = encryptor

    # ─── write ─────────────────────────────────────────────────

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
        plaintext_api_key: str,
        dek: bytes,
        model_overrides: dict[str, object] | None = None,
        region: str | None = None,
    ) -> TenantProviderCredential:
        """Create or rotate a credential.

        On a rotation (previous active row exists), the old row is
        flipped to ``active=False`` with ``rotated_at=now()`` BEFORE
        the new row is inserted — keeping the partial unique index
        happy and preserving rotation history in a single flush.
        """
        encrypted = self._encryptor.encrypt(
            plaintext_api_key.encode("utf-8"),
            dek,
            associated_data=_aad(tenant_id, provider),
        )
        # Rotate any existing active row out of the way.
        existing = await self._find_active(tenant_id, provider)
        if existing is not None:
            existing.active = False
            existing.rotated_at = datetime.now(tz=UTC)
            # Make sure the inactive flip is visible before the new
            # insert so the partial unique index doesn't fire on
            # postgres.
            await self._session.flush()

        row = TenantProviderCredential(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            encrypted_api_key=encrypted,
            model_overrides=dict(model_overrides) if model_overrides else {},
            region=region,
            active=True,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def disable(
        self,
        *,
        tenant_id: uuid.UUID,
        provider: str,
    ) -> bool:
        """Soft-disable the active credential for ``(tenant, provider)``.

        Returns ``True`` if a row was disabled, ``False`` if there was
        no active row. Idempotent — calling twice never raises.
        """
        existing = await self._find_active(tenant_id, provider)
        if existing is None:
            return False
        existing.active = False
        existing.rotated_at = datetime.now(tz=UTC)
        await self._session.flush()
        return True

    # ─── read ──────────────────────────────────────────────────

    async def get_active_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        provider: str,
        dek: bytes,
    ) -> TenantCredential | None:
        """Return the unwrapped active credential, or ``None``.

        Decryption errors propagate as :class:`CryptoError` — the
        request handler at the API layer catches it and falls back to
        platform-billed (with a WARN-level log carrying the credential
        id but not the ciphertext). See the BYOK plan's "decryption-
        error fallback" risk note.
        """
        row = await self._find_active(tenant_id, provider)
        if row is None:
            return None
        plaintext = self._encryptor.decrypt(
            row.encrypted_api_key,
            dek,
            associated_data=_aad(tenant_id, provider),
        )
        return TenantCredential(
            id=row.id,
            tenant_id=row.tenant_id,
            provider=row.provider,
            api_key=plaintext.decode("utf-8"),
            active=row.active,
            region=row.region,
            rotated_at=row.rotated_at,
        )

    async def unwrap_key(
        self,
        row: TenantProviderCredential,
        dek: bytes,
    ) -> str:
        """Decrypt a specific row's API key — for tests and admin UIs.

        Production callers should prefer :meth:`get_active_for_tenant`
        which folds the lookup + unwrap into one step."""
        plaintext = self._encryptor.decrypt(
            row.encrypted_api_key,
            dek,
            associated_data=_aad(row.tenant_id, row.provider),
        )
        return plaintext.decode("utf-8")

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        provider: str | None = None,
        include_inactive: bool = True,
    ) -> list[TenantProviderCredential]:
        """Every credential row for a tenant, optionally filtered.

        Default returns active + inactive — that's the audit / UI view.
        Pass ``include_inactive=False`` for the "active only" view.
        """
        stmt = select(TenantProviderCredential).where(
            TenantProviderCredential.tenant_id == tenant_id,
        )
        if provider is not None:
            stmt = stmt.where(TenantProviderCredential.provider == provider)
        if not include_inactive:
            stmt = stmt.where(TenantProviderCredential.active.is_(True))
        stmt = stmt.order_by(TenantProviderCredential.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ─── internal ──────────────────────────────────────────────

    async def _find_active(
        self,
        tenant_id: uuid.UUID,
        provider: str,
    ) -> TenantProviderCredential | None:
        stmt = select(TenantProviderCredential).where(
            TenantProviderCredential.tenant_id == tenant_id,
            TenantProviderCredential.provider == provider,
            TenantProviderCredential.active.is_(True),
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


def _aad(tenant_id: uuid.UUID, provider: str) -> bytes:
    """Authenticated associated-data binding for AES-GCM.

    Binds ciphertext to the ``(tenant_id, provider)`` pair so a
    cross-tenant or cross-provider blob substitution is rejected by
    the GCM auth tag.
    """
    return f"{tenant_id}|{provider}".encode()


__all__ = ["TenantCredential", "TenantProviderCredentialRepo"]

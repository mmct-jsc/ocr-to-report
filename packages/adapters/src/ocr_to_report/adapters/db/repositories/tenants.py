"""TenantRepo — create / lookup / archive."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import Tenant

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ocr_to_report.adapters.crypto import EnvelopeEncryptor


class TenantRepo:
    """Repository for the ``tenants`` table.

    Construction takes both the session and the envelope encryptor so
    the repo can mint a wrapped DEK on creation.
    """

    def __init__(self, session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
        self._session = session
        self._encryptor = encryptor

    async def create(
        self,
        *,
        name: str,
        slug: str,
        sla_tier: str = "standard",
        region_pin: str | None = None,
        default_target_system: str | None = None,
        pipeline_id: str = "default_v1",
        profiles_enabled: list[str] | None = None,
    ) -> tuple[Tenant, bytes]:
        """Create a tenant and return ``(tenant_row, dek_plain)``.

        The plaintext DEK is returned so the caller can immediately use
        it for any same-request encryption work; it is never persisted.
        """
        dek_plain, dek_wrapped = self._encryptor.new_tenant_dek_wrapped()
        tenant = Tenant(
            id=uuid.uuid4(),
            name=name,
            slug=slug,
            sla_tier=sla_tier,
            region_pin=region_pin,
            default_target_system=default_target_system,
            pipeline_id=pipeline_id,
            profiles_enabled={"profile_ids": list(profiles_enabled or [])},
            dek_wrapped=dek_wrapped,
        )
        self._session.add(tenant)
        await self._session.flush()
        return tenant, dek_plain

    async def get(self, tenant_id: uuid.UUID) -> Tenant | None:
        return await self._session.get(Tenant, tenant_id)

    async def get_by_slug(self, slug: str) -> Tenant | None:
        result = await self._session.execute(select(Tenant).where(Tenant.slug == slug))
        return result.scalar_one_or_none()

    async def list_all(self, *, include_archived: bool = False) -> list[Tenant]:
        """Cross-tenant listing for admin scope. Skips archived rows by default."""
        stmt = select(Tenant).order_by(Tenant.created_at.desc())
        if not include_archived:
            stmt = stmt.where(Tenant.archived_at.is_(None))
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(
        self,
        tenant_id: uuid.UUID,
        *,
        name: str | None = None,
        sla_tier: str | None = None,
        region_pin: str | None = None,
        default_target_system: str | None = None,
        pipeline_id: str | None = None,
    ) -> Tenant | None:
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            return None
        if name is not None:
            tenant.name = name
        if sla_tier is not None:
            tenant.sla_tier = sla_tier
        if region_pin is not None:
            tenant.region_pin = region_pin
        if default_target_system is not None:
            tenant.default_target_system = default_target_system
        if pipeline_id is not None:
            tenant.pipeline_id = pipeline_id
        return tenant

    async def unwrap_dek(self, tenant: Tenant) -> bytes:
        return self._encryptor.unwrap(tenant.dek_wrapped)

    async def archive(self, tenant_id: uuid.UUID) -> None:
        """Mark archived (does NOT crypto-shred — see :meth:`crypto_shred`)."""
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            return
        tenant.archived_at = datetime.now(tz=UTC)

    async def crypto_shred(self, tenant_id: uuid.UUID) -> None:
        """GDPR Article 17 erasure: destroy the wrapped DEK.

        Every encrypted row for this tenant becomes mathematically
        unrecoverable. Encrypted blobs and rows can be deleted at leisure
        afterward; without the DEK they're already opaque.
        """
        tenant = await self._session.get(Tenant, tenant_id)
        if tenant is None:
            return
        # Overwrite with random bytes of the same length so we can't be
        # accused of "still holding the wrapped key".
        import secrets  # noqa: PLC0415

        tenant.dek_wrapped = secrets.token_bytes(len(tenant.dek_wrapped))
        tenant.archived_at = datetime.now(tz=UTC)


__all__ = ["TenantRepo"]

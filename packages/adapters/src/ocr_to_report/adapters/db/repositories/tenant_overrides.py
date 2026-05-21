"""``TenantOverrideRepo`` — read/write per-tenant override patches.

Stateless repo over the ``tenant_overrides`` table. The override
resolver consumes ``list_for_tenant`` once per request to build the
fully-resolved view of profile / target / pipeline / SLA bundles;
the API layer's ``PUT /v1/tenant/config`` (Task 5) calls ``upsert``.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ocr_to_report.adapters.db.models import TenantOverride

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class TenantOverrideRepo:
    """Repository for the ``tenant_overrides`` table.

    The unique ``(tenant_id, scope, target_id)`` triple is the natural
    primitive — ``upsert`` is the single write path; reading is by
    tenant (optionally filtered by scope).
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: str,
        target_id: str | None,
        patches: list[dict[str, Any]],
        enabled: bool = True,
    ) -> TenantOverride:
        """Create or update the row for ``(tenant, scope, target_id)``.

        Returns the live row in either case. Patches are stored
        verbatim — validation happens at apply time via
        ``core.overrides.resolver.apply_overrides`` so the same error
        path catches malformed patches whether they came from the API
        or a direct DB import.
        """
        existing = await self._find(tenant_id, scope, target_id)
        if existing is not None:
            existing.patches = patches
            existing.enabled = enabled
            await self._session.flush()
            return existing
        row = TenantOverride(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            scope=scope,
            target_id=target_id,
            patches=patches,
            enabled=enabled,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_for_tenant(
        self,
        tenant_id: uuid.UUID,
        *,
        scope: str | None = None,
        include_disabled: bool = False,
    ) -> list[TenantOverride]:
        """Return every override row for a tenant.

        Default behaviour mirrors what the request-time resolver needs:
        enabled rows only, optionally narrowed to one scope. Pass
        ``include_disabled=True`` for admin/UI views that want to show
        toggled-off rows.
        """
        stmt = select(TenantOverride).where(TenantOverride.tenant_id == tenant_id)
        if not include_disabled:
            stmt = stmt.where(TenantOverride.enabled.is_(True))
        if scope is not None:
            stmt = stmt.where(TenantOverride.scope == scope)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(
        self,
        *,
        tenant_id: uuid.UUID,
        scope: str,
        target_id: str | None,
    ) -> bool:
        """Hard-delete the row at ``(tenant, scope, target_id)``.

        Returns True if a row was removed, False if no row matched.
        The toggleable ``enabled`` flag is the soft-disable path; this
        method is for when the operator really wants the row gone.
        """
        existing = await self._find(tenant_id, scope, target_id)
        if existing is None:
            return False
        await self._session.delete(existing)
        await self._session.flush()
        return True

    async def _find(
        self,
        tenant_id: uuid.UUID,
        scope: str,
        target_id: str | None,
    ) -> TenantOverride | None:
        stmt = select(TenantOverride).where(
            TenantOverride.tenant_id == tenant_id,
            TenantOverride.scope == scope,
        )
        # NULL comparisons need explicit ``IS NULL`` rather than ``=``.
        if target_id is None:
            stmt = stmt.where(TenantOverride.target_id.is_(None))
        else:
            stmt = stmt.where(TenantOverride.target_id == target_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()


__all__ = ["TenantOverrideRepo"]

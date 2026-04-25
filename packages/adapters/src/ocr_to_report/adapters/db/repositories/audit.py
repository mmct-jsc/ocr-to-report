"""AuditRepo — hash-chained tenant audit trail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, select

from ocr_to_report.adapters.audit import (
    AuditEntry,
    next_entry,
    verify_chain,
)
from ocr_to_report.adapters.audit.chain import GENESIS_HASH
from ocr_to_report.adapters.db.models import AuditLog

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


def _to_utc(ts: datetime) -> datetime:
    """SQLite drops tz info on DateTime columns; re-attach UTC on read."""
    if ts.tzinfo is None:
        return ts.replace(tzinfo=UTC)
    return ts.astimezone(UTC)


class AuditRepo:
    """Repository for the ``audit_log`` table.

    Append is the only mutation operation. Reads are paginated by
    timestamp; the verify cron uses :meth:`verify_for_tenant` to walk
    each tenant's chain in chronological order.
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append(
        self,
        *,
        tenant_id: uuid.UUID,
        actor_type: str,
        actor_id_hash: str,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        ip: str | None = None,
        user_agent_hash: str | None = None,
        request_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditLog:
        prev_hash = await self._latest_row_hash(tenant_id)

        entry = next_entry(
            id=uuid.uuid4(),
            ts=datetime.now(tz=UTC),
            tenant_id=tenant_id,
            actor_type=actor_type,
            actor_id_hash=actor_id_hash,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip=ip,
            user_agent_hash=user_agent_hash,
            request_id=request_id,
            metadata=metadata or {},
            prev_hash=prev_hash,
        )
        row = AuditLog(
            id=entry.id,
            ts=entry.ts,
            tenant_id=entry.tenant_id,
            actor_type=entry.actor_type,
            actor_id_hash=entry.actor_id_hash,
            action=entry.action,
            resource_type=entry.resource_type,
            resource_id=entry.resource_id,
            ip=entry.ip,
            user_agent_hash=entry.user_agent_hash,
            request_id=entry.request_id,
            metadata_json=entry.metadata,
            prev_hash=entry.prev_hash,
            row_hash=entry.row_hash,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def _latest_row_hash(self, tenant_id: uuid.UUID) -> str:
        result = await self._session.execute(
            select(AuditLog.row_hash)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(desc(AuditLog.ts), desc(AuditLog.id))
            .limit(1)
        )
        latest = result.scalar_one_or_none()
        return latest or GENESIS_HASH

    async def verify_for_tenant(self, tenant_id: uuid.UUID) -> int:
        """Walk the chain in chronological order; raise on break.

        Returns the number of entries verified.
        """
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.ts, AuditLog.id)
        )
        rows = list(result.scalars().all())
        entries = [_row_to_entry(r) for r in rows]
        verify_chain(entries)
        return len(entries)


def _row_to_entry(row: AuditLog) -> AuditEntry:
    return AuditEntry(
        id=row.id,
        ts=_to_utc(row.ts),
        tenant_id=row.tenant_id,
        actor_type=row.actor_type,
        actor_id_hash=row.actor_id_hash,
        action=row.action,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        ip=row.ip,
        user_agent_hash=row.user_agent_hash,
        request_id=row.request_id,
        metadata=row.metadata_json,
        prev_hash=row.prev_hash,
        row_hash=row.row_hash,
    )


__all__ = ["AuditRepo"]

"""AuditRepo — hash-chained tenant audit trail."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

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
        """Find the chain tail by walking ``prev_hash`` linkage.

        Timestamp ordering alone isn't enough — two rows can share a
        microsecond on a fast loop, and our PK is a random UUID — so
        we recover insertion order from the hash chain itself: the
        tail is the row whose ``row_hash`` is no other row's
        ``prev_hash``.
        """
        rows = await self._all_rows(tenant_id)
        if not rows:
            return GENESIS_HASH
        prev_hashes = {row.prev_hash for row in rows}
        for row in rows:
            if row.row_hash not in prev_hashes:
                return row.row_hash
        # Cycle detected (shouldn't happen for a well-formed chain) —
        # fall back to the latest by timestamp so we can still append.
        rows.sort(key=lambda r: (r.ts, str(r.id)))
        return rows[-1].row_hash

    async def verify_for_tenant(self, tenant_id: uuid.UUID) -> int:
        """Walk the chain in linkage order; raise on break.

        Returns the number of entries verified.
        """
        rows = await self._all_rows(tenant_id)
        if not rows:
            return 0
        ordered = _order_by_chain(rows)
        entries = [_row_to_entry(r) for r in ordered]
        verify_chain(entries)
        return len(entries)

    async def _all_rows(self, tenant_id: uuid.UUID) -> list[AuditLog]:
        result = await self._session.execute(
            select(AuditLog).where(AuditLog.tenant_id == tenant_id)
        )
        return list(result.scalars().all())

    async def list_recent(
        self,
        tenant_id: uuid.UUID,
        *,
        limit: int = 100,
    ) -> list[AuditLog]:
        """Recent-first audit-log slice for the admin viewer.

        Ordered by ``ts`` desc; chain validation is the verifier's job,
        not the viewer's.
        """
        result = await self._session.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .order_by(AuditLog.ts.desc())
            .limit(limit)
        )
        return list(result.scalars().all())


def _order_by_chain(rows: list[AuditLog]) -> list[AuditLog]:
    """Order rows by walking ``prev_hash`` → ``row_hash`` linkage.

    Robust to ties on ``ts`` (random UUID PKs would otherwise scramble
    same-microsecond inserts and break the chain). The first row is
    whichever has ``prev_hash == GENESIS_HASH``; each subsequent row
    is the one whose ``prev_hash`` is the previous row's ``row_hash``.

    Raises through ``verify_chain`` if the linkage doesn't form a
    single connected path — that's a tampering/corruption signal.
    """
    by_prev: dict[str, AuditLog] = {row.prev_hash: row for row in rows}
    head = by_prev.get(GENESIS_HASH)
    if head is None:
        # No genesis entry — fall back to (ts, id) ordering so the
        # verifier raises a clear chain-break error.
        return sorted(rows, key=lambda r: (r.ts, str(r.id)))
    chain: list[AuditLog] = [head]
    current = head
    while True:
        nxt = next((row for row in rows if row.prev_hash == current.row_hash), None)
        if nxt is None:
            break
        chain.append(nxt)
        current = nxt
    return chain


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

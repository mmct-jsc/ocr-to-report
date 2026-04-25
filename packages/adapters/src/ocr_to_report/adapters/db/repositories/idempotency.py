"""IdempotencyRepo — replay-safe POST cache (24h default TTL)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from ocr_to_report.adapters.db.models import IdempotencyKey

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class IdempotencyRepo:
    """Repository for the ``idempotency_keys`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(
        self,
        *,
        tenant_id: uuid.UUID,
        key: str,
        request_hash: str | None = None,
    ) -> IdempotencyKey | None:
        """Return the cached row iff it exists, hasn't expired, and (when
        ``request_hash`` is provided) the hashed request matches."""
        now = datetime.now(tz=UTC)
        result = await self._session.execute(
            select(IdempotencyKey).where(
                IdempotencyKey.tenant_id == tenant_id,
                IdempotencyKey.key == key,
                IdempotencyKey.expires_at > now,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        if request_hash is not None and row.request_hash != request_hash:
            return None
        return row

    async def store(
        self,
        *,
        tenant_id: uuid.UUID,
        key: str,
        request_hash: str,
        response_status: int,
        response_body: bytes,
        response_content_type: str,
        expires_at: datetime,
    ) -> IdempotencyKey:
        row = IdempotencyKey(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            key=key,
            request_hash=request_hash,
            response_status=response_status,
            response_body=response_body,
            response_content_type=response_content_type,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def purge_expired(self) -> int:
        now = datetime.now(tz=UTC)
        result = await self._session.execute(
            delete(IdempotencyKey).where(IdempotencyKey.expires_at <= now)
        )
        # `Result` typing varies by dialect; rowcount is always populated
        # for DELETE in practice but typed as Any.
        return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["IdempotencyRepo"]

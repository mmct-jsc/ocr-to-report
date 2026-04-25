"""ApiKeyRepo — issue, authenticate, revoke."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.crypto import (
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from ocr_to_report.adapters.db.models import ApiKey

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


class ApiKeyRepo:
    """Repository for the ``api_keys`` table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def issue(
        self,
        *,
        tenant_id: uuid.UUID,
        scopes: list[str],
        label: str | None = None,
        live: bool = False,
        expires_at: datetime | None = None,
        ip_allowlist: list[str] | None = None,
    ) -> tuple[ApiKey, str]:
        """Mint a fresh API key. Returns ``(row, plaintext_key)``.

        The plaintext key is returned exactly once; only its hash is
        persisted. Caller must surface it to the user immediately and
        never store it.
        """
        key = generate_api_key(live=live)
        row = ApiKey(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            prefix=api_key_prefix(key),
            key_hash=hash_api_key(key),
            label=label,
            scopes={"scopes": scopes},
            ip_allowlist={"cidrs": ip_allowlist} if ip_allowlist else None,
            expires_at=expires_at,
        )
        self._session.add(row)
        await self._session.flush()
        return row, key

    async def authenticate(self, presented_key: str) -> ApiKey | None:
        """Look up + verify a presented key. Returns the row on success.

        Strategy: filter by prefix (cheap index lookup), then verify
        Argon2id over the candidates. Argon2id is intentionally slow,
        so narrowing by prefix first matters.
        """
        prefix = api_key_prefix(presented_key)
        rows = (
            (
                await self._session.execute(
                    select(ApiKey).where(ApiKey.prefix == prefix, ApiKey.revoked_at.is_(None))
                )
            )
            .scalars()
            .all()
        )
        now = datetime.now(tz=UTC)
        for row in rows:
            if row.expires_at is not None and row.expires_at < now:
                continue
            if verify_api_key(presented_key, row.key_hash):
                row.last_used_at = now
                return row
        return None

    async def revoke(self, api_key_id: uuid.UUID) -> None:
        row = await self._session.get(ApiKey, api_key_id)
        if row is None or row.revoked_at is not None:
            return
        row.revoked_at = datetime.now(tz=UTC)


__all__ = ["ApiKeyRepo"]

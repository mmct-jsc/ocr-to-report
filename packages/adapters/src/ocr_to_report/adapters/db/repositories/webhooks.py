"""WebhookRepo — manage outgoing webhook subscriptions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from ocr_to_report.adapters.db.models import Webhook

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ocr_to_report.adapters.crypto import EnvelopeEncryptor


class WebhookRepo:
    """Repository for the ``webhooks`` table.

    Webhook signing secrets are encrypted with the tenant DEK so a DB
    dump leak can't be replayed against the tenant's webhook receivers.
    """

    def __init__(self, session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
        self._session = session
        self._encryptor = encryptor

    async def create(
        self,
        *,
        tenant_id: uuid.UUID,
        url: str,
        events: list[str],
        secret_plain: bytes,
        dek: bytes,
        active: bool = True,
    ) -> Webhook:
        secret_encrypted = self._encryptor.encrypt(
            secret_plain, dek, associated_data=str(tenant_id).encode()
        )
        row = Webhook(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            url=url,
            secret_encrypted=secret_encrypted,
            events={"events": events},
            active=active,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def list_active(self, tenant_id: uuid.UUID, *, event: str | None = None) -> list[Webhook]:
        result = await self._session.execute(
            select(Webhook).where(
                Webhook.tenant_id == tenant_id,
                Webhook.active.is_(True),
            )
        )
        rows = list(result.scalars().all())
        if event is None:
            return rows
        return [r for r in rows if event in (r.events.get("events") or [])]

    async def secret(self, webhook: Webhook, dek: bytes) -> bytes:
        return self._encryptor.decrypt(
            webhook.secret_encrypted,
            dek,
            associated_data=str(webhook.tenant_id).encode(),
        )

    async def mark_delivery(self, webhook_id: uuid.UUID, status: str) -> None:
        row = await self._session.get(Webhook, webhook_id)
        if row is None:
            return
        row.last_delivery_status = status
        row.last_delivered_at = datetime.now(tz=UTC)


__all__ = ["WebhookRepo"]

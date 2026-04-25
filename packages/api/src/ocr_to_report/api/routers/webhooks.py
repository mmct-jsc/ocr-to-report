"""Webhook subscription endpoints."""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, status

from ocr_to_report.api.deps import RequestRepos, get_repos
from ocr_to_report.api.schemas import (
    WebhookCreateRequest,
    WebhookCreateResponse,
    WebhookSummary,
)

router = APIRouter(prefix="/v1", tags=["webhooks"])


@router.post(
    "/webhooks",
    response_model=WebhookCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_webhook(
    body: WebhookCreateRequest,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> WebhookCreateResponse:
    secret_plain = secrets.token_bytes(32)
    row = await repos.webhooks.create(
        tenant_id=repos.tenant.id,
        url=str(body.url),
        events=list(body.events),
        secret_plain=secret_plain,
        dek=repos.dek,
    )
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="webhook.create",
        resource_type="webhook",
        resource_id=str(row.id),
    )
    return WebhookCreateResponse(
        id=row.id,
        url=row.url,
        events=list(body.events),
        active=row.active,
        last_delivery_status=row.last_delivery_status,
        last_delivered_at=row.last_delivered_at,
        created_at=row.created_at,
        signing_secret=secret_plain.hex(),
    )


@router.get("/webhooks", response_model=list[WebhookSummary])
async def list_webhooks(
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> list[WebhookSummary]:
    rows = await repos.webhooks.list_active(repos.tenant.id)
    return [
        WebhookSummary(
            id=r.id,
            url=r.url,
            events=list(r.events.get("events", [])),
            active=r.active,
            last_delivery_status=r.last_delivery_status,
            last_delivered_at=r.last_delivered_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


__all__ = ["router"]

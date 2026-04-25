"""Webhook endpoint schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StringConstraints

EventName = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z][a-z0-9._]*$", min_length=3, max_length=64),
]


class WebhookCreateRequest(BaseModel):
    """POST /v1/webhooks request body."""

    model_config = ConfigDict(extra="forbid")

    url: HttpUrl
    events: list[EventName] = Field(min_length=1, max_length=20)


class WebhookSummary(BaseModel):
    """Webhook as exposed to API consumers (no secret)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    last_delivery_status: str | None
    last_delivered_at: datetime | None
    created_at: datetime


class WebhookCreateResponse(WebhookSummary):
    """Same as :class:`WebhookSummary` plus the freshly-issued signing secret.

    The secret is returned exactly once. Subsequent reads of the
    webhook never expose it.
    """

    signing_secret: str
    """Hex-encoded signing secret. Use HMAC-SHA256 to verify deliveries."""


__all__ = [
    "EventName",
    "WebhookCreateRequest",
    "WebhookCreateResponse",
    "WebhookSummary",
]

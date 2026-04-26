"""Admin endpoint request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TenantSummary(BaseModel):
    """Compact tenant view for admin listings."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    name: str
    slug: str
    sla_tier: str
    region_pin: str | None = None
    default_target_system: str | None = None
    pipeline_id: str
    created_at: datetime
    archived_at: datetime | None = None


class TenantCreateRequest(BaseModel):
    """Body for `POST /v1/admin/tenants`."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(
        min_length=1,
        max_length=120,
        pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$",
        description="URL-safe identifier; lowercase alphanumeric + hyphens.",
    )
    sla_tier: Literal["economy", "standard", "premium", "enterprise"] = "standard"
    region_pin: str | None = None
    default_target_system: str | None = None
    pipeline_id: str = "default_v1"


class TenantUpdateRequest(BaseModel):
    """Body for `PATCH /v1/admin/tenants/{id}`."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    sla_tier: Literal["economy", "standard", "premium", "enterprise"] | None = None
    region_pin: str | None = None
    default_target_system: str | None = None
    pipeline_id: str | None = None


class ApiKeySummary(BaseModel):
    """Compact API-key view for admin listings (no secret)."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    tenant_id: uuid.UUID
    prefix: str
    label: str | None = None
    scopes: list[str]
    created_at: datetime
    last_used_at: datetime | None = None
    revoked_at: datetime | None = None
    expires_at: datetime | None = None


class ApiKeyIssueRequest(BaseModel):
    """Body for `POST /v1/admin/tenants/{id}/api-keys`."""

    model_config = ConfigDict(extra="forbid")

    label: str | None = Field(default=None, max_length=120)
    scopes: list[str] = Field(
        default_factory=lambda: ["transcripts:write"],
        description="Scope list. Use ['admin:*'] for cross-tenant admin keys.",
    )
    live: bool = Field(
        default=False,
        description="If True, mints a `sk_live_...` key; otherwise `sk_test_...`.",
    )


class ApiKeyIssueResponse(BaseModel):
    """Reply to a mint request — secret returned exactly once."""

    model_config = ConfigDict(extra="forbid")

    api_key: ApiKeySummary
    secret: str = Field(description="The plaintext API key. Save it now.")


class AuditEntrySummary(BaseModel):
    """Compact audit-log row for the admin viewer."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    ts: datetime
    actor_type: str
    action: str
    resource_type: str
    resource_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SystemOverview(BaseModel):
    """Top-of-funnel system stats for the admin dashboard."""

    model_config = ConfigDict(extra="forbid")

    tenants_total: int
    tenants_active: int
    api_keys_active: int
    profiles_loaded: list[str]
    targets_loaded: list[str]
    sla_presets: list[str]
    queue_depth: int
    api_version: str


__all__ = [
    "ApiKeyIssueRequest",
    "ApiKeyIssueResponse",
    "ApiKeySummary",
    "AuditEntrySummary",
    "SystemOverview",
    "TenantCreateRequest",
    "TenantSummary",
    "TenantUpdateRequest",
]

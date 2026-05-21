"""Pydantic response models for the SDK.

Mirrors the API's response schemas but lives in the SDK so callers
don't have to install the server-side ``ocr-to-report-api`` package.
The shapes are stable across the v1 API; new fields appear with
defaults and ``extra='ignore'`` keeps old SDK versions readable on
newer servers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class JobSummary(BaseModel):
    """Compact representation of a job."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    status: str
    profile_id: str | None = None
    target_id: str | None = None
    target_template_key: str | None = None
    pipeline_id: str
    provider_used: str | None = None
    model_id_used: str | None = None
    tokens_input: int = 0
    tokens_output: int = 0
    usd_cost: float = 0.0
    error_detail: str | None = None
    park_reason: str | None = None
    output_blob_key: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None
    expires_at: datetime | None = None


class TranscriptExtractionResponse(BaseModel):
    """Body of POST /v1/transcripts (sync)."""

    model_config = ConfigDict(extra="ignore")

    job: JobSummary
    extraction: dict[str, Any] = Field(default_factory=dict)
    overall_confidence: float
    warnings: list[str] = Field(default_factory=list)


class BatchAcceptedResponse(BaseModel):
    """Body of POST /v1/transcripts:batch (async, 202)."""

    model_config = ConfigDict(extra="ignore")

    jobs: list[JobSummary]
    accepted_count: int
    rejected: list[str] = Field(default_factory=list)


class WebhookCreateResponse(BaseModel):
    """Body of POST /v1/webhooks (includes the one-time signing secret)."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    signing_secret: str


class WebhookSummary(BaseModel):
    """Body of GET /v1/webhooks (no secret)."""

    model_config = ConfigDict(extra="ignore")

    id: uuid.UUID
    url: str
    events: list[str]
    active: bool
    last_delivery_status: str | None = None
    last_delivered_at: datetime | None = None


class UsageResponse(BaseModel):
    """Body of GET /v1/usage."""

    model_config = ConfigDict(extra="ignore")

    period_start: datetime
    period_end: datetime
    transcripts_processed: int
    tokens_input: int
    tokens_output: int
    cache_read_tokens: int
    cache_creation_tokens: int
    usd_cost: float


class TemplateInfo(BaseModel):
    """Per-template metadata inside a target listing."""

    model_config = ConfigDict(extra="ignore")

    key: str
    output_format: str
    target_year_index: int


class TargetInfo(BaseModel):
    """One target system in the templates listing."""

    model_config = ConfigDict(extra="ignore")

    target_id: str
    name: str
    version: str
    output_language: str
    output_formats: list[str]
    templates: list[TemplateInfo]


class TemplatesResponse(BaseModel):
    """Body of GET /v1/templates."""

    model_config = ConfigDict(extra="ignore")

    targets: list[TargetInfo]


class CustomTemplateResponse(BaseModel):
    """Body of POST /v1/templates/{target_id}/{template_key}.

    The ``blob_key`` is the storage key the server picked — it embeds
    the upload's sha256 so re-uploading the same bytes is idempotent at
    the blob layer. SDK callers can treat it as opaque.
    """

    model_config = ConfigDict(extra="ignore")

    target_id: str
    template_key: str
    blob_key: str
    sha256: str
    size_bytes: int


# ─── Tenant config (override patches) ────────────────────────


class TenantConfigUpdate(BaseModel):
    """Body for PUT /v1/tenant/config and POST /v1/tenant/config:preview.

    Every field is optional — sending ``{"sla_patches": [...]}`` replaces
    JUST the SLA patches and leaves profile/target rows alone. To clear
    a scope, send an explicit empty list.

    ``pipeline_id`` is the one direct tenant column written by this
    endpoint — pass a pipeline id to switch the tenant's active pipeline.
    """

    model_config = ConfigDict(extra="ignore")

    pipeline_id: str | None = None
    sla_patches: list[dict[str, Any]] | None = None
    profile_overrides: dict[str, list[dict[str, Any]]] | None = None
    target_overrides: dict[str, list[dict[str, Any]]] | None = None


class TenantConfigResponse(BaseModel):
    """Body of GET /v1/tenant/config + POST /v1/tenant/config:preview.

    ``sla`` is the tier preset with any ``sla_patches`` applied. The raw
    patch lists ride alongside so a UI can render its diff editor
    without re-deriving from the resolved view.
    """

    model_config = ConfigDict(extra="ignore")

    sla: dict[str, Any]
    pipeline_id: str
    sla_patches: list[dict[str, Any]] = Field(default_factory=list)
    profile_overrides: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    target_overrides: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


__all__ = [
    "BatchAcceptedResponse",
    "CustomTemplateResponse",
    "JobSummary",
    "TargetInfo",
    "TemplateInfo",
    "TemplatesResponse",
    "TenantConfigResponse",
    "TenantConfigUpdate",
    "TranscriptExtractionResponse",
    "UsageResponse",
    "WebhookCreateResponse",
    "WebhookSummary",
]

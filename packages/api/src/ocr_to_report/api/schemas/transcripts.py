"""Transcript endpoint request/response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TranscriptJobSummary(BaseModel):
    """Compact representation of a job — used in list/status responses."""

    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    status: str
    profile_id: str | None
    target_id: str | None
    target_template_key: str | None
    pipeline_id: str
    provider_used: str | None
    model_id_used: str | None
    tokens_input: int
    tokens_output: int
    usd_cost: float
    error_detail: str | None
    park_reason: str | None
    output_blob_key: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    expires_at: datetime | None


class TranscriptExtractionResponse(BaseModel):
    """Body of a successful sync POST /v1/transcripts response.

    Contains the canonical extraction in JSON form plus a job summary;
    the rendered xlsx is returned via ``GET /v1/jobs/{id}/result``.
    """

    model_config = ConfigDict(extra="forbid")

    job: TranscriptJobSummary
    extraction: dict[str, Any] = Field(
        description="The CanonicalTranscript serialized to JSON.",
    )
    overall_confidence: float = Field(ge=0.0, le=1.0)
    warnings: list[str] = Field(default_factory=list)


class BatchAcceptedResponse(BaseModel):
    """Body of a successful POST /v1/transcripts:batch response.

    The request was queued; results are delivered via webhook
    (``job.completed``) or polled via ``GET /v1/jobs/{id}``. Half-cost
    Anthropic Batch SLA: completes within 24h.
    """

    model_config = ConfigDict(extra="forbid")

    jobs: list[TranscriptJobSummary] = Field(
        description="One summary per accepted file. Status is 'pending' on accept.",
    )
    accepted_count: int = Field(ge=0)
    rejected: list[str] = Field(
        default_factory=list,
        description="Filenames that were rejected (with the reason).",
    )


__all__ = [
    "BatchAcceptedResponse",
    "TranscriptExtractionResponse",
    "TranscriptJobSummary",
]

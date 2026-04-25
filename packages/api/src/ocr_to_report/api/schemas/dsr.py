"""GDPR Data Subject Request response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class DSRAccessResponse(BaseModel):
    """GDPR Article 15 — Right of Access.

    Returns every record the controller holds *about* a data subject
    (identified by ``subject_full_name``) within the tenant's dataset.
    """

    model_config = ConfigDict(extra="forbid")

    subject_full_name: str
    tenant_id: uuid.UUID
    generated_at: datetime
    record_count: int = Field(ge=0)
    transcripts: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Decrypted CanonicalTranscript snapshots that match.",
    )


class DSRPortabilityResponse(BaseModel):
    """GDPR Article 20 — Right to Portability.

    Same payload as Article 15 but with a stable, machine-readable
    schema version so the export survives tooling changes.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["dsr.portability.v1"] = "dsr.portability.v1"
    subject_full_name: str
    tenant_id: uuid.UUID
    generated_at: datetime
    transcripts: list[dict[str, Any]] = Field(default_factory=list)


class DSRErasureRequest(BaseModel):
    """GDPR Article 17 — Right to Erasure (request body)."""

    model_config = ConfigDict(extra="forbid")

    subject_full_name: str = Field(
        min_length=1,
        max_length=200,
        description="Full name of the data subject to erase.",
    )
    confirm: Literal[True] = Field(
        description="Must be set to True to authorize the destructive operation.",
    )


class DSRErasureResponse(BaseModel):
    """Result of an erasure operation."""

    model_config = ConfigDict(extra="forbid")

    subject_full_name: str
    tenant_id: uuid.UUID
    transcripts_erased: int
    blobs_erased: int
    audit_entry_id: uuid.UUID
    completed_at: datetime


__all__ = [
    "DSRAccessResponse",
    "DSRErasureRequest",
    "DSRErasureResponse",
    "DSRPortabilityResponse",
]

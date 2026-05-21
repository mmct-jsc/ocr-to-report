"""Per-tenant custom template schemas."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class CustomTemplateResponse(BaseModel):
    """Response body for ``POST /v1/templates/{target_id}/{template_key}``.

    The returned ``blob_key`` is the storage key chosen by the server —
    it embeds the upload's sha256 so re-uploading the same bytes
    produces a stable key, while changing one cell produces a new key.
    The web UI doesn't need to interpret it; it's surfaced for support
    diagnostics.
    """

    model_config = ConfigDict(extra="forbid")

    target_id: str = Field(description="Target system id (e.g., ``us-hs.v1``).")
    template_key: str = Field(description="Template key within the target (e.g., ``grade_9``).")
    blob_key: str = Field(description="Storage key the uploaded xlsx was written to.")
    sha256: str = Field(description="SHA-256 hex digest of the uploaded bytes.")
    size_bytes: int = Field(ge=0, description="Size of the uploaded xlsx in bytes.")


__all__ = ["CustomTemplateResponse"]

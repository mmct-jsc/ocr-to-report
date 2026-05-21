"""Request / response models for ``/v1/tenant/providers``.

The BYOK API surface is intentionally small in v0.3.0:

* ``GET`` returns one ``ProviderStatus`` per provider with the API key
  REDACTED. The plaintext is never echoed back, not even to the tenant
  that supplied it. ``api_key_redacted`` is shaped ``sk-ant-…XXXX`` so
  the UI can label the row "your key ending in XXXX" without exposing
  the full string.
* ``PUT`` accepts ``{api_key, model_overrides?, region?}`` — same shape
  the repo writes. v0.3.0 validates only the anthropic provider; others
  return 501.
* ``DELETE`` has no body — soft-disables the active row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# The legal provider set is duplicated here (rather than imported from
# ``adapters.vision``) so the API schema stays self-contained — a v0.7.0
# adapter rename does not need a schema-breaking change. Wire ids are
# stable independent of the implementation.
ProviderId = Literal["anthropic", "openai", "google_vertex", "tesseract"]


class ProviderStatus(BaseModel):
    """A single redacted row in the GET response."""

    model_config = ConfigDict(extra="forbid")

    provider: ProviderId
    active: bool
    """Whether the credential is currently routable. False for
    soft-disabled rows; the UI still shows them so the tenant can see
    they had a key once."""
    api_key_redacted: str | None = None
    """``sk-ant-…XXXX`` style — last four characters only. None when no
    credential has ever been set for this provider."""
    region: str | None = None
    """Provider region pin (v0.3.0: surfaced but not acted upon)."""
    rotated_at: datetime | None = None
    """When the credential was last rotated (set on the OLD row at
    rotation time). None on a never-rotated active row."""
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ProvidersListResponse(BaseModel):
    """GET ``/v1/tenant/providers`` body."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ProviderStatus] = Field(default_factory=list)


class ProviderUpsertRequest(BaseModel):
    """PUT ``/v1/tenant/providers/{provider}`` body."""

    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=8, max_length=512)
    """The provider API key. Stored envelope-encrypted; never logged.
    Min 8 chars so a typo'd empty/short string fails at the schema
    layer with a 422 (clear) rather than reaching the validation call
    and looking like an auth failure (confusing)."""
    model_overrides: dict[str, str] | None = None
    """Optional per-call model swaps; v0.3.0 stores but does not read."""
    region: str | None = Field(default=None, max_length=64)


__all__ = [
    "ProviderId",
    "ProviderStatus",
    "ProviderUpsertRequest",
    "ProvidersListResponse",
]

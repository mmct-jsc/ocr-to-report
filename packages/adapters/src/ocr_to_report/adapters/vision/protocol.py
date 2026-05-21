"""Vision adapter protocol — the single interface every provider implements.

Concrete providers (Anthropic, OpenAI, Google, Tesseract) live in sibling
modules. The router picks among them based on the policy configured on the
tenant's SLA. The mapping engine in `core/mapping/` then translates the
raw extraction dict into a :class:`CanonicalTranscript`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class VisionProvider(StrEnum):
    """Stable provider identifiers used in cache keys and metrics."""

    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    GOOGLE = "google"
    TESSERACT = "tesseract"
    MOCK = "mock"


@dataclass(frozen=True, slots=True)
class TokenUsage:
    """Per-call token + cost accounting.

    All fields default to 0 so providers that don't expose all signals
    (e.g., Tesseract has no token concept) can populate just the relevant
    fields. ``usd_cost`` is computed from per-provider price tables.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    usd_cost: float = 0.0


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Adapter-agnostic result of extracting a profile-shaped dict from images.

    Attributes:
        raw_extraction: The dict matching the profile's ``extraction_schema``.
            Field names are profile-defined; the mapping engine consumes this.
        confidence: Aggregate extraction confidence in [0, 1]. Producers
            either compute this from per-field confidences or ask the
            model to emit it directly. Used by the router for fallback.
        field_confidences: Optional per-field confidence map. None if the
            provider does not surface field-level confidence.
        warnings: Non-fatal issues the provider noted (e.g., low-quality
            image, unreadable section). Surfaced into the canonical
            transcript's ``extraction_warnings``.
        provider: Which provider produced this result.
        model_id: Model identifier used (e.g., 'claude-haiku-4-5').
        usage: Token + cost accounting for billing.
        cache_hit: True if this result came from the result cache.
    """

    raw_extraction: dict[str, Any]
    confidence: float
    field_confidences: dict[str, float] | None
    warnings: list[str]
    provider: VisionProvider
    model_id: str
    usage: TokenUsage
    cache_hit: bool = False


@dataclass(frozen=True, slots=True)
class VisionRequest:
    """The fully-prepared input to a vision adapter call.

    Profiles are not passed directly — the caller compiles the profile's
    extraction schema into a JSON Schema and renders the prompt template,
    then hands the result to the adapter. Keeps the adapter independent
    of the profile types.
    """

    images: list[bytes]
    """Pre-processed image bytes (PNG, with EXIF stripped). One per page."""
    prompt: str
    """Fully-rendered system prompt with profile-specific guidance."""
    output_schema: dict[str, Any]
    """JSON Schema the adapter passes to the model (or validates against)."""
    schema_version: str
    """Version of the schema, used in cache key construction."""
    profile_id: str
    """Source profile id, used for metrics + cache key."""
    extra: dict[str, Any] = field(default_factory=dict)
    """Provider-specific options (e.g., max_tokens override)."""


@runtime_checkable
class VisionAdapter(Protocol):
    """Every vision provider implements this protocol.

    Implementations MUST be safe to share across concurrent requests
    (asyncio-safe). Construction may take config but must not perform I/O
    until ``extract`` is called for the first time.
    """

    name: VisionProvider
    """Provider identifier."""

    async def extract(
        self,
        request: VisionRequest,
        *,
        override_api_key: str | None = None,
    ) -> ExtractionResult:
        """Extract structured data from the request's images.

        Implementations should:
        - Validate the response against ``request.output_schema``.
        - Translate provider errors into core exceptions
          (:class:`VisionProviderError`, :class:`OperationTimeoutError`,
          :class:`CircuitOpenError`).
        - Never mutate the request.

        ``override_api_key`` (v0.3.0 BYOK): when set, the adapter
        constructs a per-call provider client using this credential
        instead of the long-lived platform client. Implementations
        that do not support per-call credentials may ignore it (the
        stub adapters do exactly that — they raise from extract()
        before any client is touched).
        """
        ...

    async def aclose(self) -> None:
        """Release provider-specific resources (HTTP clients, etc.).

        Idempotent. Default implementations may be no-ops.
        """
        ...


__all__ = [
    "ExtractionResult",
    "TokenUsage",
    "VisionAdapter",
    "VisionProvider",
    "VisionRequest",
]

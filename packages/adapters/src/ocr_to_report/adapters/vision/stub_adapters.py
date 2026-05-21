"""Stub adapters for OpenAI / Google / Tesseract.

Each implements the :class:`VisionAdapter` protocol so the router can
select among them, but ``extract()`` raises
:class:`ProviderNotConfiguredError` (HTTP 503) with a clear message
until the body lands in v1.1.

This is deliberate: the protocol contract is locked in MVP. Migrating
from the stub to the real implementation requires zero call-site changes.
"""

from __future__ import annotations

from ocr_to_report.adapters.vision.protocol import (
    ExtractionResult,
    VisionAdapter,
    VisionProvider,
    VisionRequest,
)
from ocr_to_report.core.errors.domain import ProviderNotConfiguredError


class _NotImplementedAdapter(VisionAdapter):
    """Shared scaffolding for the deferred providers."""

    name: VisionProvider
    _human_name: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        # Construction succeeds so registry tests can probe the type
        # without raising. Only extract() raises.
        return

    async def extract(
        self,
        request: VisionRequest,
        *,
        override_api_key: str | None = None,
    ) -> ExtractionResult:
        # ``override_api_key`` is accepted for protocol compatibility
        # (v0.3.0 threads it through ``VisionAdapter.extract``); the
        # stub doesn't reach a network call and ignores it. When the
        # real adapter ships in v0.7.0 it will honour BYOK like
        # AnthropicVisionAdapter does.
        del override_api_key
        raise ProviderNotConfiguredError(
            f"{self._human_name} vision adapter is scaffolded but not yet "
            "implemented. Set ANTHROPIC_API_KEY to use Claude, or wait "
            "for v1.1.",
            provider=self.name.value,
        )

    async def aclose(self) -> None:
        return None


class OpenAIVisionAdapter(_NotImplementedAdapter):
    """OpenAI gpt-4o / gpt-4o-mini vision adapter — scaffold only.

    Production interface: same as :class:`AnthropicVisionAdapter`. Will
    use OpenAI structured outputs (``response_format={"type":
    "json_schema", ...}``) and prompt-caching headers when available.
    """

    name: VisionProvider = VisionProvider.OPENAI
    _human_name = "OpenAI"


class GoogleVisionAdapter(_NotImplementedAdapter):
    """Google Gemini 2.x Flash / Pro vision adapter — scaffold only.

    Production interface: same as :class:`AnthropicVisionAdapter`. Useful
    for tenants requiring EU/Asia data-residency via Vertex AI regional
    endpoints.
    """

    name: VisionProvider = VisionProvider.GOOGLE
    _human_name = "Google Gemini"


class TesseractAdapter(_NotImplementedAdapter):
    """Local Tesseract OCR + LLM-free schema parser — scaffold only.

    Production interface: same as :class:`AnthropicVisionAdapter`, but
    extraction is performed entirely on-prem (no third-party API). Lower
    accuracy on decorative documents; suitable for air-gapped deployments.
    """

    name: VisionProvider = VisionProvider.TESSERACT
    _human_name = "Tesseract"


__all__ = [
    "GoogleVisionAdapter",
    "OpenAIVisionAdapter",
    "TesseractAdapter",
]

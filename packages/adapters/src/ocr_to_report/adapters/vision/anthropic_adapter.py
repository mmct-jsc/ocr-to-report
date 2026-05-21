"""Claude vision adapter — primary provider in MVP.

Implementation choices:

* **Tiered model selection**: a primary model handles >95% of requests; if
  the result's self-reported confidence falls below a configurable
  threshold, the request is retried against a stronger model. Default
  primary is Haiku 4.5; default fallback is Sonnet 4.6.
* **Structured outputs**: every call uses ``output_config.format`` with a
  JSON schema, guaranteeing the model returns parseable JSON matching the
  profile's extraction schema.
* **Prompt caching**: the (deterministic) system prompt plus the JSON
  schema are placed before any volatile content with a single
  ``cache_control`` breakpoint, cutting input cost ~90% on warm requests.
* **Confidence + warnings via schema**: the schema is wrapped in a
  ``_meta`` envelope that requires the model to emit overall confidence,
  per-field confidence, and free-text warnings alongside the extraction.
* **Cost tracking**: every call returns the tokens consumed and a USD
  cost computed from the per-model price table below.

The adapter is **stateless** beyond the AsyncAnthropic client; it is safe
to share a single instance across concurrent requests.
"""

from __future__ import annotations

import base64
import contextlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, cast

from ocr_to_report.adapters.vision.protocol import (
    ExtractionResult,
    TokenUsage,
    VisionProvider,
    VisionRequest,
)
from ocr_to_report.core.errors.domain import (
    CircuitOpenError,
    OperationTimeoutError,
    ValidationError,
    VisionProviderError,
)

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic
    from anthropic.types import Message


# ─── Pricing ──────────────────────────────────────────────────
# Per-1M-token pricing (USD) sourced from the published Anthropic price
# list at design time. Bumping this is a routine maintenance change; the
# adapter is intentionally side-effect free with regard to pricing so
# rates can be updated without touching call sites.
@dataclass(frozen=True, slots=True)
class _ModelPrice:
    input_per_mtok: float
    output_per_mtok: float
    cache_write_multiplier: float = 1.25
    cache_read_multiplier: float = 0.1


_PRICES: Final[dict[str, _ModelPrice]] = {
    "claude-haiku-4-5": _ModelPrice(input_per_mtok=1.0, output_per_mtok=5.0),
    "claude-sonnet-4-6": _ModelPrice(input_per_mtok=3.0, output_per_mtok=15.0),
    "claude-opus-4-7": _ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0),
    "claude-opus-4-6": _ModelPrice(input_per_mtok=5.0, output_per_mtok=25.0),
}


def _usd_cost(model: str, usage: TokenUsage) -> float:
    """Compute the dollar cost from token counts. Returns 0.0 for unknown models."""
    if model not in _PRICES:
        return 0.0
    p = _PRICES[model]
    base_input_rate = p.input_per_mtok / 1_000_000
    return (
        usage.input_tokens * base_input_rate
        + usage.output_tokens * (p.output_per_mtok / 1_000_000)
        + usage.cache_creation_input_tokens * base_input_rate * p.cache_write_multiplier
        + usage.cache_read_input_tokens * base_input_rate * p.cache_read_multiplier
    )


# ─── Schema envelope ──────────────────────────────────────────
_META_KEY: Final[str] = "_meta"


def _wrap_schema(extraction_schema: dict[str, Any]) -> dict[str, Any]:
    """Add a ``_meta`` envelope so the model emits confidence + warnings.

    The model returns ``{"<profile fields>": ..., "_meta": {"confidence":
    0.0..1.0, "field_confidences": {...}, "warnings": [...]}``. We then
    strip ``_meta`` from the raw extraction before handing it to the
    mapping engine, preserving the shape contract the profile declares.
    """
    actual_type = extraction_schema.get("type")
    if actual_type != "object":
        raise ValidationError(
            f"extraction_schema must be a JSON object schema, got {actual_type!r}",
        )
    properties = dict(extraction_schema.get("properties") or {})
    required = list(extraction_schema.get("required") or [])

    # Anthropic's output_config.format.schema is a strict subset of
    # JSON Schema:
    # * ``minimum`` / ``maximum`` on numeric types are rejected — express
    #   the [0, 1] range in the description and clamp on the way out.
    # * ``additionalProperties`` may only be the literal ``false`` (a
    #   sub-schema isn't allowed). That kills the natural shape for
    #   ``field_confidences`` (map of name → number), so we drop the
    #   field for now; the overall ``confidence`` + ``warnings`` carry
    #   the same signal the gate cares about.
    properties[_META_KEY] = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "confidence": {
                "type": "number",
                "description": (
                    "Overall extraction confidence as a number in [0, 1]. "
                    "Reflect honesty about ambiguous fields and image quality."
                ),
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Brief notes about anything unclear, illegible, or assumed.",
            },
        },
        "required": ["confidence", "warnings"],
    }
    if _META_KEY not in required:
        required.append(_META_KEY)

    return {
        **extraction_schema,
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _unwrap_response(
    response_json: dict[str, Any],
) -> tuple[dict[str, Any], float, dict[str, float] | None, list[str]]:
    """Pull confidence, field_confidences, and warnings out of ``_meta``;
    return the rest as the raw extraction.

    The Anthropic JSON-schema flavor doesn't enforce numeric range, so
    we clamp confidences to [0, 1] here as belt-and-suspenders before
    they reach the downstream Pydantic models that *do* enforce it.
    """
    meta = response_json.pop(_META_KEY, {}) or {}
    confidence = max(0.0, min(1.0, float(meta.get("confidence", 0.0))))
    field_confidences = meta.get("field_confidences")
    if field_confidences is not None:
        field_confidences = {k: max(0.0, min(1.0, float(v))) for k, v in field_confidences.items()}
    warnings = list(meta.get("warnings", []) or [])
    return response_json, confidence, field_confidences, warnings


# ─── Adapter ──────────────────────────────────────────────────
class AnthropicVisionAdapter:
    """Tiered Claude vision adapter."""

    name: VisionProvider = VisionProvider.ANTHROPIC

    def __init__(
        self,
        client: AsyncAnthropic,
        *,
        primary_model: str = "claude-haiku-4-5",
        fallback_model: str | None = "claude-sonnet-4-6",
        confidence_threshold: float = 0.85,
        max_output_tokens: int = 4096,
    ) -> None:
        if not 0.0 <= confidence_threshold <= 1.0:
            raise ValueError("confidence_threshold must be in [0, 1]")
        self._client = client
        self._primary_model = primary_model
        self._fallback_model = fallback_model
        self._confidence_threshold = confidence_threshold
        self._max_output_tokens = max_output_tokens

    async def extract(
        self,
        request: VisionRequest,
        *,
        override_api_key: str | None = None,
    ) -> ExtractionResult:
        """Run the tiered extraction.

        ``override_api_key`` (v0.3.0 BYOK): when set, a one-shot
        :class:`AsyncAnthropic` client is constructed with that key and
        used for BOTH the primary attempt AND any confidence-gated
        fallback. The platform's shared client is never touched. The
        one-shot client is closed at the end of the call so BYOK
        traffic does not leak httpx connections.
        """
        wrapped = _wrap_schema(request.output_schema)
        client, own_client = await self._client_for(override_api_key)
        try:
            # Primary attempt
            result = await self._call(
                client=client,
                model=self._primary_model,
                request=request,
                schema=wrapped,
            )

            # Fallback if confidence below threshold and a stronger model is configured.
            if (
                self._fallback_model is not None
                and self._fallback_model != self._primary_model
                and result.confidence < self._confidence_threshold
            ):
                fallback = await self._call(
                    client=client,
                    model=self._fallback_model,
                    request=request,
                    schema=wrapped,
                )
                # Combine cost (we did pay for both calls); take the fallback's
                # extraction since it's the higher-confidence one.
                combined_usage = _combine_usage(result.usage, fallback.usage)
                return ExtractionResult(
                    raw_extraction=fallback.raw_extraction,
                    confidence=fallback.confidence,
                    field_confidences=fallback.field_confidences,
                    warnings=[*fallback.warnings, *_promote_primary_warnings(result.warnings)],
                    provider=VisionProvider.ANTHROPIC,
                    model_id=self._fallback_model,
                    usage=combined_usage,
                )
            return result
        finally:
            if own_client:
                # Best-effort close. The plain ``await client.aclose()``
                # is the right call against a real AsyncAnthropic; the
                # try/except keeps tests with non-async mocks usable.
                aclose = getattr(client, "aclose", None)
                if aclose is not None:
                    with contextlib.suppress(TypeError):  # mocks may not be awaitable
                        await aclose()

    async def _client_for(
        self,
        override_api_key: str | None,
    ) -> tuple[AsyncAnthropic, bool]:
        """Return ``(client, owned)`` for this extract() call.

        ``owned=True`` means the adapter constructed a one-shot client
        and is responsible for closing it before returning.
        """
        if override_api_key is None:
            return self._client, False
        # Lazy import so the package can be imported without the
        # anthropic SDK installed in tests that don't touch this path.
        import anthropic  # noqa: PLC0415

        fresh = anthropic.AsyncAnthropic(api_key=override_api_key)
        return fresh, True

    async def aclose(self) -> None:
        # AsyncAnthropic owns its own httpx client; closing here would
        # break callers that share the client. Leave it to the caller.
        # Per-call BYOK clients are closed inside extract() — they
        # never reach this method.
        return None

    # ── Internals ────────────────────────────────────────────
    async def _call(
        self,
        *,
        client: AsyncAnthropic,
        model: str,
        request: VisionRequest,
        schema: dict[str, Any],
    ) -> ExtractionResult:
        # Lazy import so the package can be imported in environments that
        # haven't installed the anthropic SDK (e.g., tests using only
        # OpenAI/Tesseract adapters).
        import anthropic  # noqa: PLC0415

        image_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }
            for img in request.images
        ]

        # System prompt + JSON schema are deterministic and shared across
        # calls; cache breakpoint goes on the schema (rendered last in the
        # system block) to capture both at once.
        system_blocks = [
            {"type": "text", "text": request.prompt},
            {
                "type": "text",
                "text": (
                    "Always return JSON matching this schema. The "
                    "`_meta` field is REQUIRED — populate `confidence` "
                    "honestly based on document quality, and list any "
                    "uncertainties under `warnings`.\n\n"
                    f"```json\n{json.dumps(schema, sort_keys=True)}\n```"
                ),
                "cache_control": {"type": "ephemeral"},
            },
        ]

        # The system/messages payloads are well-typed JSON structures;
        # the SDK's TypedDict shapes can't validate every nested form
        # (e.g., conditional cache_control), so we cast to Any at the
        # boundary. Failure modes are caught by runtime API errors below.
        try:
            message: Message = await client.messages.create(
                model=model,
                max_tokens=self._max_output_tokens,
                system=cast("Any", system_blocks),
                messages=cast(
                    "Any",
                    [
                        {
                            "role": "user",
                            "content": [
                                *image_blocks,
                                {
                                    "type": "text",
                                    "text": (
                                        "Extract the requested data from the "
                                        "image(s) above. Return JSON only — "
                                        "no prose, no markdown."
                                    ),
                                },
                            ],
                        },
                    ],
                ),
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APITimeoutError as e:
            raise OperationTimeoutError(
                f"Anthropic vision call timed out: {e}",
                model=model,
            ) from e
        except anthropic.RateLimitError as e:
            raise CircuitOpenError(
                f"Anthropic rate limit exceeded: {e}",
                model=model,
            ) from e
        except anthropic.APIStatusError as e:
            raise VisionProviderError(
                f"Anthropic API error ({e.status_code}): {e.message}",
                model=model,
                status_code=e.status_code,
            ) from e
        except anthropic.APIConnectionError as e:
            raise VisionProviderError(
                f"Anthropic API connection error: {e}",
                model=model,
            ) from e

        return self._build_result(message, model)

    def _build_result(self, message: Message, model: str) -> ExtractionResult:
        text = _extract_text(message)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise VisionProviderError(
                f"Anthropic returned non-JSON despite output_config.format: {e}",
                model=model,
                response_preview=text[:500],
            ) from e
        if not isinstance(payload, dict):
            raise VisionProviderError(
                f"Anthropic returned a {type(payload).__name__}, expected an object",
                model=model,
            )

        raw_extraction, confidence, field_confidences, warnings = _unwrap_response(payload)

        usage = TokenUsage(
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
            cache_creation_input_tokens=getattr(message.usage, "cache_creation_input_tokens", 0)
            or 0,
            cache_read_input_tokens=getattr(message.usage, "cache_read_input_tokens", 0) or 0,
        )
        usage = _attach_cost(usage, model)

        return ExtractionResult(
            raw_extraction=raw_extraction,
            confidence=confidence,
            field_confidences=field_confidences,
            warnings=warnings,
            provider=VisionProvider.ANTHROPIC,
            model_id=model,
            usage=usage,
        )


def _extract_text(message: Message) -> str:
    """Concatenate every text block in the response."""
    from anthropic.types import TextBlock  # noqa: PLC0415

    parts: list[str] = [block.text for block in message.content if isinstance(block, TextBlock)]
    if not parts:
        raise VisionProviderError(
            "Anthropic response contained no text blocks",
            model=message.model,
        )
    return "".join(parts)


def _attach_cost(usage: TokenUsage, model: str) -> TokenUsage:
    return TokenUsage(
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_creation_input_tokens=usage.cache_creation_input_tokens,
        cache_read_input_tokens=usage.cache_read_input_tokens,
        usd_cost=_usd_cost(model, usage),
    )


def _combine_usage(a: TokenUsage, b: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        cache_creation_input_tokens=a.cache_creation_input_tokens + b.cache_creation_input_tokens,
        cache_read_input_tokens=a.cache_read_input_tokens + b.cache_read_input_tokens,
        usd_cost=a.usd_cost + b.usd_cost,
    )


def _promote_primary_warnings(warnings: list[str]) -> list[str]:
    """Annotate warnings from the primary (lower-confidence) attempt so
    they're distinguishable from the fallback's warnings in audit logs."""
    return [f"[primary attempt low confidence] {w}" for w in warnings]


__all__ = ["AnthropicVisionAdapter"]

"""Vision adapter protocol contract tests."""

from __future__ import annotations

from ocr_to_report.adapters.vision import (
    AnthropicVisionAdapter,
    ExtractionResult,
    GoogleVisionAdapter,
    OpenAIVisionAdapter,
    TesseractAdapter,
    TokenUsage,
    VisionAdapter,
    VisionProvider,
    VisionRequest,
)


def test_token_usage_defaults_to_zero() -> None:
    u = TokenUsage()
    assert u.input_tokens == 0
    assert u.output_tokens == 0
    assert u.usd_cost == 0.0


def test_extraction_result_is_frozen() -> None:
    import dataclasses  # noqa: PLC0415

    import pytest  # noqa: PLC0415

    r = ExtractionResult(
        raw_extraction={"x": 1},
        confidence=0.9,
        field_confidences=None,
        warnings=[],
        provider=VisionProvider.MOCK,
        model_id="mock",
        usage=TokenUsage(),
    )
    assert r.cache_hit is False
    assert dataclasses.is_dataclass(ExtractionResult)
    # Frozen dataclass: attribute assignment raises FrozenInstanceError
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.confidence = 0.5  # type: ignore[misc]


def test_vision_request_extra_optional() -> None:
    req = VisionRequest(
        images=[b"png"],
        prompt="extract",
        output_schema={
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
        schema_version="1.0",
        profile_id="pl.x.v1",
    )
    assert req.extra == {}


def test_stub_adapters_are_protocol_compliant() -> None:
    # runtime_checkable Protocol — the stubs implement extract / aclose / name
    for cls in (OpenAIVisionAdapter, GoogleVisionAdapter, TesseractAdapter):
        adapter = cls()
        assert isinstance(adapter, VisionAdapter)
        assert isinstance(adapter.name, VisionProvider)


def test_anthropic_adapter_construction_does_not_call_provider() -> None:
    """Adapter __init__ must not perform I/O — protocol invariant."""
    from anthropic import AsyncAnthropic  # noqa: PLC0415

    client = AsyncAnthropic(api_key="sk-test", base_url="http://localhost:1")
    adapter = AnthropicVisionAdapter(
        client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
    )
    assert adapter.name is VisionProvider.ANTHROPIC


def test_anthropic_adapter_validates_confidence_threshold() -> None:
    import pytest  # noqa: PLC0415
    from anthropic import AsyncAnthropic  # noqa: PLC0415

    client = AsyncAnthropic(api_key="sk-test", base_url="http://localhost:1")
    with pytest.raises(ValueError):
        AnthropicVisionAdapter(client, confidence_threshold=1.5)
    with pytest.raises(ValueError):
        AnthropicVisionAdapter(client, confidence_threshold=-0.1)

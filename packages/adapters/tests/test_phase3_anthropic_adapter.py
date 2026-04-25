"""AnthropicVisionAdapter behavior tests with mocked AsyncAnthropic.

These tests do NOT call the real Anthropic API; they replace
``client.messages.create`` with an AsyncMock and assert on the adapter's
control-flow logic: schema wrapping, confidence-gated fallback, error
translation, cost computation, and result construction.

End-to-end live tests (gated by ``LIVE_TESTS=1``) exercise the real API
in nightly CI; cassette-based replay tests record once and replay
deterministically thereafter.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ocr_to_report.adapters.vision import (
    AnthropicVisionAdapter,
    VisionProvider,
    VisionRequest,
)


def _fake_message(text: str, *, model: str, usage: dict[str, int]) -> Any:
    """Build a fake anthropic.types.Message-shaped object."""
    from anthropic.types import TextBlock  # noqa: PLC0415

    msg = MagicMock()
    msg.model = model
    block = MagicMock(spec=TextBlock)
    block.type = "text"
    block.text = text
    msg.content = [block]
    msg.usage = MagicMock(
        input_tokens=usage.get("input_tokens", 100),
        output_tokens=usage.get("output_tokens", 50),
        cache_creation_input_tokens=usage.get("cache_creation_input_tokens", 0),
        cache_read_input_tokens=usage.get("cache_read_input_tokens", 0),
    )
    return msg


def _payload(*, confidence: float, warnings: list[str] | None = None) -> str:
    return json.dumps(
        {
            "full_name": "Jan Kowalski",
            "subjects": [{"raw_subject_name": "Math", "raw_grade_value": "5"}],
            "_meta": {
                "confidence": confidence,
                "warnings": warnings or [],
                "field_confidences": {"full_name": 0.99},
            },
        }
    )


def _request() -> VisionRequest:
    return VisionRequest(
        images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 100],  # placeholder
        prompt="extract data",
        output_schema={
            "type": "object",
            "properties": {
                "full_name": {"type": "string"},
                "subjects": {"type": "array"},
            },
            "required": ["full_name", "subjects"],
            "additionalProperties": False,
        },
        schema_version="1.0",
        profile_id="pl.lo.swiadectwo_szkolne.v1",
    )


# ─── Single-call path ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_high_confidence_no_fallback() -> None:
    client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 1000, "output_tokens": 200},
        )
    )
    client.messages.create = create
    adapter = AnthropicVisionAdapter(
        client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )

    result = await adapter.extract(_request())

    create.assert_awaited_once()
    assert create.await_args is not None
    assert create.await_args.kwargs["model"] == "claude-haiku-4-5"
    assert result.confidence == 0.95
    assert result.model_id == "claude-haiku-4-5"
    assert result.provider is VisionProvider.ANTHROPIC
    assert result.usage.input_tokens == 1000
    assert result.usage.output_tokens == 200
    # Cost = 1000 * $1/1M + 200 * $5/1M = $0.001 + $0.001 = $0.002
    assert result.usage.usd_cost == pytest.approx(0.002, abs=1e-9)


# ─── Confidence-gated fallback ────────────────────────────────
@pytest.mark.asyncio
async def test_low_confidence_triggers_fallback() -> None:
    client = MagicMock()
    primary_msg = _fake_message(
        _payload(confidence=0.50, warnings=["faded scan"]),
        model="claude-haiku-4-5",
        usage={"input_tokens": 800, "output_tokens": 150},
    )
    fallback_msg = _fake_message(
        _payload(confidence=0.95, warnings=["resolved on retry"]),
        model="claude-sonnet-4-6",
        usage={"input_tokens": 800, "output_tokens": 150},
    )
    client.messages.create = AsyncMock(side_effect=[primary_msg, fallback_msg])
    adapter = AnthropicVisionAdapter(
        client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )

    result = await adapter.extract(_request())

    assert client.messages.create.await_count == 2
    # Models called in order
    assert client.messages.create.await_args_list[0].kwargs["model"] == "claude-haiku-4-5"
    assert client.messages.create.await_args_list[1].kwargs["model"] == "claude-sonnet-4-6"
    # Result reflects the fallback
    assert result.model_id == "claude-sonnet-4-6"
    assert result.confidence == 0.95
    # Combined cost = haiku call + sonnet call
    # haiku: 800/1M*$1 + 150/1M*$5 = $0.0008 + $0.00075 = $0.00155
    # sonnet: 800/1M*$3 + 150/1M*$15 = $0.0024 + $0.00225 = $0.00465
    assert result.usage.usd_cost == pytest.approx(0.0062, rel=1e-3)
    # Combined token totals
    assert result.usage.input_tokens == 1600
    assert result.usage.output_tokens == 300
    # Primary warnings annotated and combined with fallback warnings
    assert any("faded scan" in w for w in result.warnings)
    assert any("primary attempt low confidence" in w for w in result.warnings)
    assert "resolved on retry" in result.warnings


@pytest.mark.asyncio
async def test_no_fallback_when_threshold_met() -> None:
    """Confidence exactly at threshold should NOT trigger fallback."""
    client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.85),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    client.messages.create = create
    adapter = AnthropicVisionAdapter(
        client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )
    await adapter.extract(_request())
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_no_fallback_when_disabled() -> None:
    client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.30),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    client.messages.create = create
    adapter = AnthropicVisionAdapter(
        client,
        primary_model="claude-haiku-4-5",
        fallback_model=None,  # disabled
        confidence_threshold=0.85,
    )
    result = await adapter.extract(_request())
    assert create.await_count == 1
    assert result.confidence == 0.30


# ─── Schema envelope ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_schema_wrapped_with_meta_envelope() -> None:
    client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    client.messages.create = create
    adapter = AnthropicVisionAdapter(
        client,
        fallback_model=None,
    )
    await adapter.extract(_request())

    assert create.await_args is not None
    sent_schema = create.await_args.kwargs["output_config"]["format"]["schema"]
    assert "_meta" in sent_schema["properties"]
    assert "_meta" in sent_schema["required"]
    meta = sent_schema["properties"]["_meta"]
    assert "confidence" in meta["properties"]
    assert "warnings" in meta["properties"]


@pytest.mark.asyncio
async def test_meta_stripped_from_raw_extraction() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    adapter = AnthropicVisionAdapter(client, fallback_model=None)
    result = await adapter.extract(_request())
    assert "_meta" not in result.raw_extraction
    assert result.raw_extraction["full_name"] == "Jan Kowalski"


# ─── Error translation ────────────────────────────────────────
@pytest.mark.asyncio
async def test_timeout_translated_to_domain_error() -> None:
    import anthropic  # noqa: PLC0415

    from ocr_to_report.core.errors.domain import OperationTimeoutError  # noqa: PLC0415

    client = MagicMock()
    client.messages.create = AsyncMock(side_effect=anthropic.APITimeoutError(request=MagicMock()))
    adapter = AnthropicVisionAdapter(client, fallback_model=None)
    with pytest.raises(OperationTimeoutError):
        await adapter.extract(_request())


@pytest.mark.asyncio
async def test_rate_limit_translated_to_circuit_open() -> None:
    import anthropic  # noqa: PLC0415

    from ocr_to_report.core.errors.domain import CircuitOpenError  # noqa: PLC0415

    client = MagicMock()
    rate_err = anthropic.RateLimitError(
        message="rate limit",
        response=MagicMock(headers={}),
        body=None,
    )
    client.messages.create = AsyncMock(side_effect=rate_err)
    adapter = AnthropicVisionAdapter(client, fallback_model=None)
    with pytest.raises(CircuitOpenError):
        await adapter.extract(_request())


@pytest.mark.asyncio
async def test_invalid_json_response_raises() -> None:
    from ocr_to_report.core.errors.domain import VisionProviderError  # noqa: PLC0415

    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_fake_message(
            "not valid json",
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    adapter = AnthropicVisionAdapter(client, fallback_model=None)
    with pytest.raises(VisionProviderError):
        await adapter.extract(_request())


# ─── Cache headers ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_cache_control_attached_to_system_block() -> None:
    client = MagicMock()
    client.messages.create = AsyncMock(
        return_value=_fake_message(
            _payload(confidence=0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    adapter = AnthropicVisionAdapter(client, fallback_model=None)
    await adapter.extract(_request())

    assert client.messages.create.await_args is not None
    system = client.messages.create.await_args.kwargs["system"]
    # The schema-bearing system block must carry cache_control: ephemeral
    schema_blocks = [b for b in system if "cache_control" in b]
    assert len(schema_blocks) == 1
    assert schema_blocks[0]["cache_control"] == {"type": "ephemeral"}

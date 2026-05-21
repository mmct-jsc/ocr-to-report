"""``VisionAdapter.extract`` accepts a per-call API key override (v0.3.0).

The BYOK request path threads a tenant-supplied Anthropic API key from
the request handler down to the adapter. The adapter MUST:

1. When ``override_api_key`` is ``None``, route through the long-lived
   platform client (the constructor-bound ``AsyncAnthropic``).
2. When ``override_api_key`` is a string, construct a one-shot
   ``AsyncAnthropic(api_key=...)`` for that call only. The platform
   client is never touched.

This isolates BYOK so:

* The platform's connection pool / rate-limit state is not impacted.
* A bad tenant key only fails that tenant's request; it cannot poison
  the shared client.
* Logging / metrics can be attributed correctly per call.

The stub adapters (OpenAI / Google / Tesseract) also accept the kwarg
so the v0.7.0 swap from stub → real for those providers is a same-
signature change.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ocr_to_report.adapters.vision import (
    AnthropicVisionAdapter,
    VisionProvider,
    VisionRequest,
)


def _fake_message(text: str, *, model: str, usage: dict[str, int]) -> Any:
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


def _payload(confidence: float = 0.95) -> str:
    return json.dumps(
        {
            "full_name": "Jan Kowalski",
            "subjects": [],
            "_meta": {"confidence": confidence, "warnings": []},
        }
    )


def _request() -> VisionRequest:
    return VisionRequest(
        images=[b"\x89PNG\r\n\x1a\n" + b"\x00" * 100],
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


@pytest.mark.asyncio
async def test_override_none_uses_platform_client() -> None:
    """With no override, the long-lived platform client handles the call.

    Verified by checking that ``client.messages.create`` was invoked on
    the platform client instance — and that no fresh client was
    constructed."""
    platform_client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 100, "output_tokens": 50},
        )
    )
    platform_client.messages.create = create
    adapter = AnthropicVisionAdapter(
        platform_client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )

    with patch("anthropic.AsyncAnthropic") as fresh_ctor:
        result = await adapter.extract(_request(), override_api_key=None)

    create.assert_awaited_once()
    # No fresh client was constructed — the platform client was used.
    fresh_ctor.assert_not_called()
    assert result.provider is VisionProvider.ANTHROPIC


@pytest.mark.asyncio
async def test_override_constructs_one_shot_client_with_key() -> None:
    """When ``override_api_key`` is set, a fresh ``AsyncAnthropic`` is
    constructed with that key and used in place of the platform client.

    Asserted via the constructor's recorded kwargs — the test does not
    actually hit Anthropic.
    """
    platform_client = MagicMock()
    platform_create = AsyncMock()
    platform_client.messages.create = platform_create

    # The "fresh" client that the override path constructs. Its
    # messages.create returns a normal high-confidence fake response.
    fresh_create = AsyncMock(
        return_value=_fake_message(
            _payload(0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 200, "output_tokens": 75},
        )
    )
    fresh_client = MagicMock()
    fresh_client.messages.create = fresh_create
    # The adapter closes its one-shot override client; the mock needs an
    # awaitable aclose for that to work.
    fresh_client.aclose = AsyncMock()

    adapter = AnthropicVisionAdapter(
        platform_client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )

    with patch("anthropic.AsyncAnthropic", return_value=fresh_client) as fresh_ctor:
        result = await adapter.extract(
            _request(),
            override_api_key="sk-ant-tenant-key-XYZ",
        )

    # Fresh client constructed with the tenant's key.
    fresh_ctor.assert_called_once()
    assert fresh_ctor.call_args.kwargs.get("api_key") == "sk-ant-tenant-key-XYZ"

    # The fresh client's messages.create was invoked; the platform
    # client's was NOT.
    fresh_create.assert_awaited_once()
    platform_create.assert_not_awaited()

    # Result still carries the provider + model normally.
    assert result.provider is VisionProvider.ANTHROPIC
    assert result.model_id == "claude-haiku-4-5"


@pytest.mark.asyncio
async def test_override_threads_through_fallback_call_too() -> None:
    """If the fallback model fires (low-confidence primary), it must use
    the SAME override key — not silently revert to the platform client.

    Otherwise a BYOK tenant could end up billing the platform for their
    fallback half-call, which is a billing bug, not just an accounting
    one.
    """
    platform_client = MagicMock()
    platform_create = AsyncMock()
    platform_client.messages.create = platform_create

    # Fresh client: primary call returns low confidence; fallback call
    # returns high confidence.
    primary_msg = _fake_message(
        _payload(0.50),
        model="claude-haiku-4-5",
        usage={"input_tokens": 100, "output_tokens": 50},
    )
    fallback_msg = _fake_message(
        _payload(0.95),
        model="claude-sonnet-4-6",
        usage={"input_tokens": 100, "output_tokens": 50},
    )
    fresh_create = AsyncMock(side_effect=[primary_msg, fallback_msg])
    fresh_client = MagicMock()
    fresh_client.messages.create = fresh_create
    # The adapter closes its one-shot override client; the mock needs an
    # awaitable aclose for that to work.
    fresh_client.aclose = AsyncMock()

    adapter = AnthropicVisionAdapter(
        platform_client,
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
    )

    with patch("anthropic.AsyncAnthropic", return_value=fresh_client) as fresh_ctor:
        result = await adapter.extract(
            _request(),
            override_api_key="sk-ant-fallback-test",
        )

    # Both primary + fallback rode the fresh client.
    assert fresh_create.await_count == 2
    platform_create.assert_not_awaited()
    # The constructor was called only once: the fresh client is
    # reused across primary + fallback for a single request.
    assert fresh_ctor.call_count == 1
    assert result.model_id == "claude-sonnet-4-6"


@pytest.mark.asyncio
async def test_extract_protocol_compatibility() -> None:
    """The signature ``extract(request, *, override_api_key=None)`` is
    keyword-only — existing call sites that pass only ``request``
    continue to work unchanged.

    The protocol's default for ``override_api_key`` is ``None``.
    """
    platform_client = MagicMock()
    create = AsyncMock(
        return_value=_fake_message(
            _payload(0.95),
            model="claude-haiku-4-5",
            usage={"input_tokens": 50, "output_tokens": 25},
        )
    )
    platform_client.messages.create = create
    adapter = AnthropicVisionAdapter(
        platform_client,
        primary_model="claude-haiku-4-5",
        fallback_model=None,
        confidence_threshold=0.85,
    )

    # Positional-only request, no kwargs. Must not raise.
    result = await adapter.extract(_request())
    assert result.provider is VisionProvider.ANTHROPIC

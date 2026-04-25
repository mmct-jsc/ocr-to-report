"""Phase 7 — AnthropicBatchAdapter unit tests.

Drives the adapter against a faked Anthropic SDK client. The fake records
calls + returns the canonical batch shapes so we can verify:

* submit() builds correctly-shaped per-request params.
* fetch_results() handles succeeded + errored entries.
* Missing custom_ids surface as error results.
* The 50% batch discount is applied to per-item cost.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ocr_to_report.adapters.vision.anthropic_batch import (
    AnthropicBatchAdapter,
    BatchStatus,
)
from ocr_to_report.adapters.vision.protocol import VisionRequest
from ocr_to_report.core.errors.domain import VisionProviderError


# ─── Fakes ───────────────────────────────────────────────────
@dataclass(frozen=True)
class _FakeBatch:
    id: str
    processing_status: str


@dataclass(frozen=True)
class _FakeUsage:
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass(frozen=True)
class _FakeTextBlock:
    text: str
    type: str = "text"


@dataclass(frozen=True)
class _FakeMessage:
    content: list[_FakeTextBlock]
    usage: _FakeUsage
    model: str = "claude-haiku-4-5"


@dataclass(frozen=True)
class _FakeResultSucceeded:
    type: str
    message: _FakeMessage


@dataclass(frozen=True)
class _FakeResultErrored:
    type: str
    error: dict[str, Any]


@dataclass(frozen=True)
class _FakeBatchEntry:
    custom_id: str
    result: _FakeResultSucceeded | _FakeResultErrored


class _FakeAsyncStream:
    def __init__(self, entries: list[_FakeBatchEntry]) -> None:
        self._entries = entries

    def __aiter__(self) -> AsyncIterator[_FakeBatchEntry]:
        async def _gen() -> AsyncIterator[_FakeBatchEntry]:
            for entry in self._entries:
                yield entry

        return _gen()


class _FakeBatches:
    def __init__(self) -> None:
        self.create = AsyncMock(
            return_value=_FakeBatch(id="batch_abc123", processing_status="in_progress"),
        )
        self.retrieve = AsyncMock(
            return_value=_FakeBatch(id="batch_abc123", processing_status="ended"),
        )
        self.results = AsyncMock()


class _FakeMessages:
    def __init__(self) -> None:
        self.batches = _FakeBatches()


class _FakeClient:
    def __init__(self) -> None:
        self.messages = _FakeMessages()


def _make_request(image_bytes: bytes = b"PNG_FAKE_BYTES") -> VisionRequest:
    return VisionRequest(
        images=[image_bytes],
        prompt="Extract the data.",
        output_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        schema_version="1.0",
        profile_id="test.v1",
    )


def _success_payload(name: str, confidence: float = 0.92) -> str:
    return json.dumps(
        {
            "name": name,
            "_meta": {"confidence": confidence, "warnings": []},
        }
    )


# ─── Tests ───────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_submit_builds_per_request_params() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    handle = await adapter.submit(
        [
            ("job_001", _make_request(b"img1")),
            ("job_002", _make_request(b"img2")),
        ]
    )

    assert handle.batch_id == "batch_abc123"
    assert handle.custom_ids == ["job_001", "job_002"]

    create_call = client.messages.batches.create.await_args
    assert create_call is not None
    requests = create_call.kwargs["requests"]
    assert len(requests) == 2
    first = requests[0]
    assert first["custom_id"] == "job_001"
    params = first["params"]
    assert params["model"] == "claude-haiku-4-5"
    assert params["output_config"]["format"]["type"] == "json_schema"
    schema = params["output_config"]["format"]["schema"]
    assert "_meta" in schema["properties"]


@pytest.mark.asyncio
async def test_submit_empty_batch_raises() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client)  # type: ignore[arg-type]
    with pytest.raises(VisionProviderError):
        await adapter.submit([])


@pytest.mark.asyncio
async def test_get_status_normalizes_provider_strings() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client)  # type: ignore[arg-type]

    client.messages.batches.retrieve.return_value = _FakeBatch(
        id="b", processing_status="in_progress"
    )
    assert await adapter.get_status("b") is BatchStatus.IN_PROGRESS

    client.messages.batches.retrieve.return_value = _FakeBatch(id="b", processing_status="ended")
    assert await adapter.get_status("b") is BatchStatus.ENDED

    client.messages.batches.retrieve.return_value = _FakeBatch(
        id="b", processing_status="cancelled"
    )
    assert await adapter.get_status("b") is BatchStatus.CANCELED

    client.messages.batches.retrieve.return_value = _FakeBatch(id="b", processing_status="errored")
    assert await adapter.get_status("b") is BatchStatus.ERRORED


@pytest.mark.asyncio
async def test_fetch_results_parses_success_and_error_entries() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client, model="claude-haiku-4-5")  # type: ignore[arg-type]

    entries = [
        _FakeBatchEntry(
            custom_id="job_001",
            result=_FakeResultSucceeded(
                type="succeeded",
                message=_FakeMessage(
                    content=[_FakeTextBlock(text=_success_payload("Alice", 0.9))],
                    usage=_FakeUsage(input_tokens=2000, output_tokens=400),
                ),
            ),
        ),
        _FakeBatchEntry(
            custom_id="job_002",
            result=_FakeResultErrored(
                type="errored",
                error={"message": "image too small"},
            ),
        ),
    ]
    client.messages.batches.results = AsyncMock(return_value=_FakeAsyncStream(entries))

    handle = await adapter.submit(
        [
            ("job_001", _make_request(b"a")),
            ("job_002", _make_request(b"b")),
        ]
    )
    results = await adapter.fetch_results(handle)

    assert set(results.keys()) == {"job_001", "job_002"}
    success = results["job_001"]
    assert success.is_success
    assert success.extraction is not None
    assert success.extraction.raw_extraction == {"name": "Alice"}
    assert success.extraction.confidence == 0.9
    # Batch discount applied (would be ~$0.004 sync; ~$0.002 batch).
    assert 0.0 < success.extraction.usage.usd_cost < 0.004
    assert success.extraction.usage.input_tokens == 2000

    failure = results["job_002"]
    assert not failure.is_success
    assert failure.extraction is None
    assert failure.error_detail is not None
    assert "image too small" in failure.error_detail


@pytest.mark.asyncio
async def test_fetch_results_marks_missing_custom_ids_as_dropped() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client)  # type: ignore[arg-type]
    # Stream has only job_001; we'll claim we submitted 001 and 002.
    entries = [
        _FakeBatchEntry(
            custom_id="job_001",
            result=_FakeResultSucceeded(
                type="succeeded",
                message=_FakeMessage(
                    content=[_FakeTextBlock(text=_success_payload("Alice"))],
                    usage=_FakeUsage(input_tokens=100, output_tokens=20),
                ),
            ),
        ),
    ]
    client.messages.batches.results = AsyncMock(return_value=_FakeAsyncStream(entries))

    handle = await adapter.submit(
        [
            ("job_001", _make_request(b"a")),
            ("job_002", _make_request(b"b")),
        ]
    )
    results = await adapter.fetch_results(handle)
    assert results["job_001"].is_success
    assert not results["job_002"].is_success
    detail = results["job_002"].error_detail or ""
    assert "missing" in detail.lower()


@pytest.mark.asyncio
async def test_fetch_results_handles_non_json_text() -> None:
    client = _FakeClient()
    adapter = AnthropicBatchAdapter(client)  # type: ignore[arg-type]
    entries = [
        _FakeBatchEntry(
            custom_id="job_x",
            result=_FakeResultSucceeded(
                type="succeeded",
                message=_FakeMessage(
                    content=[_FakeTextBlock(text="not json at all")],
                    usage=_FakeUsage(input_tokens=10, output_tokens=2),
                ),
            ),
        ),
    ]
    client.messages.batches.results = AsyncMock(return_value=_FakeAsyncStream(entries))

    handle = await adapter.submit([("job_x", _make_request())])
    results = await adapter.fetch_results(handle)
    assert not results["job_x"].is_success
    assert results["job_x"].error_detail is not None
    assert "non-JSON" in results["job_x"].error_detail

"""Result-cache tests."""

from __future__ import annotations

import asyncio

import pytest

from ocr_to_report.adapters.vision import (
    ExtractionResult,
    InMemoryAsyncCache,
    TokenUsage,
    VisionProvider,
    deserialize_result,
    make_cache_key,
    serialize_result,
)


def _result() -> ExtractionResult:
    return ExtractionResult(
        raw_extraction={"full_name": "Jan Kowalski", "subjects": [{"x": 1}]},
        confidence=0.93,
        field_confidences={"full_name": 0.99, "subjects": 0.85},
        warnings=["faded last column"],
        provider=VisionProvider.ANTHROPIC,
        model_id="claude-haiku-4-5",
        usage=TokenUsage(
            input_tokens=2048,
            output_tokens=512,
            cache_creation_input_tokens=1500,
            cache_read_input_tokens=0,
            usd_cost=0.0123,
        ),
    )


def test_cache_key_deterministic() -> None:
    images = [b"abc", b"def"]
    a = make_cache_key(images, VisionProvider.ANTHROPIC, "1.0")
    b = make_cache_key(images, VisionProvider.ANTHROPIC, "1.0")
    assert a == b
    assert a.startswith("vision:v1:anthropic:1.0:")


def test_cache_key_changes_on_inputs() -> None:
    base = make_cache_key([b"abc"], VisionProvider.ANTHROPIC, "1.0")
    assert make_cache_key([b"abc"], VisionProvider.OPENAI, "1.0") != base
    assert make_cache_key([b"abc"], VisionProvider.ANTHROPIC, "1.1") != base
    assert make_cache_key([b"abcd"], VisionProvider.ANTHROPIC, "1.0") != base
    assert make_cache_key([b"abc", b"d"], VisionProvider.ANTHROPIC, "1.0") != base


def test_cache_key_resists_concatenation_collisions() -> None:
    """Ensure (b'ab', b'c') and (b'a', b'bc') hash differently — length-prefixed."""
    a = make_cache_key([b"ab", b"c"], VisionProvider.ANTHROPIC, "1.0")
    b = make_cache_key([b"a", b"bc"], VisionProvider.ANTHROPIC, "1.0")
    assert a != b


def test_serialize_round_trip() -> None:
    original = _result()
    blob = serialize_result(original)
    restored = deserialize_result(blob)
    assert restored.raw_extraction == original.raw_extraction
    assert restored.confidence == original.confidence
    assert restored.field_confidences == original.field_confidences
    assert restored.warnings == original.warnings
    assert restored.provider == original.provider
    assert restored.model_id == original.model_id
    assert restored.usage.input_tokens == original.usage.input_tokens
    assert restored.usage.usd_cost == original.usage.usd_cost
    # Deserialization sets cache_hit=True
    assert restored.cache_hit is True


# ─── In-memory cache ───────────────────────────────────────────
@pytest.mark.asyncio
async def test_cache_get_set_delete() -> None:
    cache = InMemoryAsyncCache()
    await cache.set("k", b"v", ttl_seconds=5)
    assert await cache.get("k") == b"v"
    await cache.delete("k")
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_cache_ttl_expires(monkeypatch: pytest.MonkeyPatch) -> None:

    fake_now = [1000.0]

    def fake_monotonic() -> float:
        return fake_now[0]

    monkeypatch.setattr("ocr_to_report.adapters.vision.result_cache.time.monotonic", fake_monotonic)

    cache = InMemoryAsyncCache()
    await cache.set("k", b"v", ttl_seconds=10)
    assert await cache.get("k") == b"v"
    fake_now[0] += 11
    assert await cache.get("k") is None


@pytest.mark.asyncio
async def test_cache_max_entries_eviction() -> None:
    cache = InMemoryAsyncCache(max_entries=3)
    await cache.set("a", b"1", ttl_seconds=10)
    await cache.set("b", b"2", ttl_seconds=20)
    await cache.set("c", b"3", ttl_seconds=30)
    # Forth insert evicts the soonest-expiring entry (a)
    await cache.set("d", b"4", ttl_seconds=40)
    # 'a' expires first -> evicted
    assert await cache.get("a") is None
    assert await cache.get("d") == b"4"


@pytest.mark.asyncio
async def test_cache_concurrent_safe() -> None:
    cache = InMemoryAsyncCache()

    async def writer(i: int) -> None:
        await cache.set(f"k{i}", str(i).encode(), ttl_seconds=10)

    async def reader(i: int) -> bytes | None:
        return await cache.get(f"k{i}")

    await asyncio.gather(*(writer(i) for i in range(50)))
    results = await asyncio.gather(*(reader(i) for i in range(50)))
    assert all(r is not None for r in results)

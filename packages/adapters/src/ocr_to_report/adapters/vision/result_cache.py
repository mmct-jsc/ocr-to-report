"""Result cache: skip the vision call entirely for duplicate inputs.

Cache key is ``sha256(image_bytes_concat) || provider || schema_version``.
Same PDF re-uploaded by the same tenant under the same profile = $0 cost,
~milliseconds latency.

The cache itself is just a key/value store interface (`AsyncCache`) so we
can drop in Redis later without touching call sites. Phase 3 ships an
in-memory implementation; Phase 5 adds the Redis backing.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ocr_to_report.adapters.vision.protocol import (
    ExtractionResult,
    TokenUsage,
    VisionProvider,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


CACHE_KEY_VERSION = "v1"
"""Bumped if the cache key derivation changes — invalidates all entries."""


def make_cache_key(
    images: Iterable[bytes],
    provider: VisionProvider,
    schema_version: str,
) -> str:
    """Deterministic cache key from inputs."""
    h = hashlib.sha256()
    for img in images:
        h.update(len(img).to_bytes(8, "big"))  # length-prefix to avoid collisions
        h.update(img)
    image_hash = h.hexdigest()
    return f"vision:{CACHE_KEY_VERSION}:{provider.value}:{schema_version}:{image_hash}"


@runtime_checkable
class AsyncCache(Protocol):
    """Minimal async key/value cache. Redis-compatible by design."""

    async def get(self, key: str) -> bytes | None: ...
    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None: ...
    async def delete(self, key: str) -> None: ...


@dataclass(slots=True)
class _Entry:
    value: bytes
    expires_at: float


class InMemoryAsyncCache:
    """Thread-safe in-memory cache with TTL.

    Suitable for single-process deployments and tests. Phase 5 swaps in a
    Redis-backed implementation that satisfies the same protocol.
    """

    def __init__(self, max_entries: int = 1024) -> None:
        self._max_entries = max_entries
        self._data: dict[str, _Entry] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> bytes | None:
        async with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.expires_at <= time.monotonic():
                self._data.pop(key, None)
                return None
            return entry.value

    async def set(self, key: str, value: bytes, *, ttl_seconds: int) -> None:
        async with self._lock:
            if len(self._data) >= self._max_entries:
                self._evict_one()
            self._data[key] = _Entry(value, time.monotonic() + ttl_seconds)

    async def delete(self, key: str) -> None:
        async with self._lock:
            self._data.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()

    def _evict_one(self) -> None:
        # Drop the entry with the soonest expiry first; if all expire at
        # roughly the same time, fall back to oldest insertion (dict order).
        soonest = min(self._data.items(), key=lambda kv: kv[1].expires_at, default=None)
        if soonest is not None:
            self._data.pop(soonest[0], None)


# ─── Serialization ────────────────────────────────────────────
def serialize_result(result: ExtractionResult) -> bytes:
    """Encode an ExtractionResult to bytes for storage in the cache."""
    payload = {
        "raw_extraction": result.raw_extraction,
        "confidence": result.confidence,
        "field_confidences": result.field_confidences,
        "warnings": result.warnings,
        "provider": result.provider.value,
        "model_id": result.model_id,
        "usage": {
            "input_tokens": result.usage.input_tokens,
            "output_tokens": result.usage.output_tokens,
            "cache_creation_input_tokens": result.usage.cache_creation_input_tokens,
            "cache_read_input_tokens": result.usage.cache_read_input_tokens,
            "usd_cost": result.usage.usd_cost,
        },
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def deserialize_result(blob: bytes) -> ExtractionResult:
    """Decode bytes into an ExtractionResult (marked as cache_hit=True)."""
    payload = json.loads(blob)
    usage = payload["usage"]
    return ExtractionResult(
        raw_extraction=payload["raw_extraction"],
        confidence=payload["confidence"],
        field_confidences=payload["field_confidences"],
        warnings=list(payload["warnings"]),
        provider=VisionProvider(payload["provider"]),
        model_id=payload["model_id"],
        usage=TokenUsage(
            input_tokens=usage["input_tokens"],
            output_tokens=usage["output_tokens"],
            cache_creation_input_tokens=usage["cache_creation_input_tokens"],
            cache_read_input_tokens=usage["cache_read_input_tokens"],
            usd_cost=usage["usd_cost"],
        ),
        cache_hit=True,
    )


__all__ = [
    "CACHE_KEY_VERSION",
    "AsyncCache",
    "InMemoryAsyncCache",
    "deserialize_result",
    "make_cache_key",
    "serialize_result",
]

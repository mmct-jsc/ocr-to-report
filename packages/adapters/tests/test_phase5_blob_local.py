"""LocalBlobStore tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ocr_to_report.adapters.blob import (
    BlobNotFoundError,
    BlobStoreError,
    LocalBlobStore,
)


@pytest.mark.asyncio
async def test_put_get_round_trip(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    meta = await store.put("docs/hello.txt", b"hi", content_type="text/plain")
    assert meta.size_bytes == 2
    assert meta.content_type == "text/plain"
    assert await store.get("docs/hello.txt") == b"hi"


@pytest.mark.asyncio
async def test_head(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    await store.put("k", b"abc")
    meta = await store.head("k")
    assert meta.size_bytes == 3


@pytest.mark.asyncio
async def test_get_missing_raises(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    with pytest.raises(BlobNotFoundError):
        await store.get("missing")


@pytest.mark.asyncio
async def test_delete_idempotent(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    await store.put("k", b"x")
    await store.delete("k")
    await store.delete("k")  # second call must not raise
    assert not await store.exists("k")


@pytest.mark.asyncio
async def test_exists(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    assert not await store.exists("k")
    await store.put("k", b"x")
    assert await store.exists("k")


@pytest.mark.asyncio
async def test_path_traversal_rejected(tmp_path: Path) -> None:
    store = LocalBlobStore(tmp_path)
    for bad in ("../escape", "/abs", "a/../../b"):
        with pytest.raises(BlobStoreError):
            await store.put(bad, b"x")

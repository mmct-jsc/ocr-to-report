"""Filesystem-backed blob store (dev + tests)."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from datetime import UTC, datetime
from pathlib import Path

from ocr_to_report.adapters.blob.protocol import (
    BlobMetadata,
    BlobNotFoundError,
    BlobStoreError,
)


class LocalBlobStore:
    """Stores blobs as files under ``root``.

    Keys are split on ``/`` to form subdirectories — same shape as S3
    paths so behavior matches once you swap backends.
    """

    def __init__(self, root: Path) -> None:
        self._root = root
        self._root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise BlobStoreError(f"invalid blob key: {key!r}")
        return self._root / key

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> BlobMetadata:
        path = self._path(key)
        await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(path.write_bytes, data)
        etag = hashlib.md5(data, usedforsecurity=False).hexdigest()
        stat = await asyncio.to_thread(path.stat)
        return BlobMetadata(
            key=key,
            size_bytes=stat.st_size,
            content_type=content_type,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            etag=etag,
        )

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise BlobNotFoundError(f"no blob at key {key!r}", key=key)
        return await asyncio.to_thread(path.read_bytes)

    async def head(self, key: str) -> BlobMetadata:
        path = self._path(key)
        if not path.is_file():
            raise BlobNotFoundError(f"no blob at key {key!r}", key=key)
        stat = await asyncio.to_thread(path.stat)
        return BlobMetadata(
            key=key,
            size_bytes=stat.st_size,
            content_type=None,
            last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        )

    async def delete(self, key: str) -> None:
        path = self._path(key)
        with contextlib.suppress(FileNotFoundError):
            await asyncio.to_thread(path.unlink)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()


__all__ = ["LocalBlobStore"]

"""Blob store protocol + shared types."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from ocr_to_report.core.errors.domain import StorageError


class BlobStoreError(StorageError):
    """Generic blob store failure."""


class BlobNotFoundError(BlobStoreError):
    """The requested blob key does not exist."""

    status = 404
    type_uri = "https://errors.ocr-to-report/blob-not-found"
    title = "Blob not found"


@dataclass(frozen=True, slots=True)
class BlobMetadata:
    key: str
    size_bytes: int
    content_type: str | None
    last_modified: datetime
    etag: str | None = None


@runtime_checkable
class BlobStore(Protocol):
    """Async key/value blob store."""

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> BlobMetadata: ...

    async def get(self, key: str) -> bytes: ...

    async def head(self, key: str) -> BlobMetadata: ...

    async def delete(self, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...


__all__ = ["BlobMetadata", "BlobNotFoundError", "BlobStore", "BlobStoreError"]

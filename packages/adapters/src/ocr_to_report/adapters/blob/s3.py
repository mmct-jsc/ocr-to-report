"""S3-compatible blob store via aioboto3.

Works against any S3-compatible service: AWS S3, MinIO, Cloudflare R2,
Google Cloud Storage's S3-compatible endpoint. The ``endpoint_url``
config knob picks among them.

The implementation deliberately keeps a single :class:`aioboto3.Session`
across the lifetime of a :class:`S3BlobStore` instance and opens a fresh
client per call — aioboto3 clients are not safe to share across
coroutines.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast

import aioboto3
from botocore.exceptions import ClientError

from ocr_to_report.adapters.blob.protocol import (
    BlobMetadata,
    BlobNotFoundError,
    BlobStoreError,
)


class S3BlobStore:
    """S3-compatible blob store."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key: str | None = None,
        secret_key: str | None = None,
    ) -> None:
        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._region = region
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    def _client_kwargs(self) -> dict[str, Any]:
        kwargs: dict[str, Any] = {"region_name": self._region}
        if self._endpoint_url:
            kwargs["endpoint_url"] = self._endpoint_url
        return kwargs

    async def put(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str | None = None,
    ) -> BlobMetadata:
        async with self._session.client("s3", **self._client_kwargs()) as client:
            put_kwargs: dict[str, Any] = {"Bucket": self._bucket, "Key": key, "Body": data}
            if content_type:
                put_kwargs["ContentType"] = content_type
            try:
                resp = await client.put_object(**put_kwargs)
            except ClientError as e:
                raise BlobStoreError(f"s3 put failed: {e}", key=key) from e
        etag = cast("str | None", resp.get("ETag"))
        return BlobMetadata(
            key=key,
            size_bytes=len(data),
            content_type=content_type,
            last_modified=datetime.now(tz=UTC),
            etag=etag.strip('"') if etag else None,
        )

    async def get(self, key: str) -> bytes:
        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                resp = await client.get_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                if _is_no_such_key(e):
                    raise BlobNotFoundError(f"no blob at key {key!r}", key=key) from e
                raise BlobStoreError(f"s3 get failed: {e}", key=key) from e
            body = resp["Body"]
            return cast("bytes", await body.read())

    async def head(self, key: str) -> BlobMetadata:
        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                resp = await client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                if _is_no_such_key(e):
                    raise BlobNotFoundError(f"no blob at key {key!r}", key=key) from e
                raise BlobStoreError(f"s3 head failed: {e}", key=key) from e
        return BlobMetadata(
            key=key,
            size_bytes=int(resp.get("ContentLength", 0)),
            content_type=resp.get("ContentType"),
            last_modified=resp.get("LastModified") or datetime.now(tz=UTC),
            etag=str(resp.get("ETag", "")).strip('"') or None,
        )

    async def delete(self, key: str) -> None:
        async with self._session.client("s3", **self._client_kwargs()) as client:
            try:
                await client.delete_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                raise BlobStoreError(f"s3 delete failed: {e}", key=key) from e

    async def exists(self, key: str) -> bool:
        try:
            await self.head(key)
        except BlobNotFoundError:
            return False
        return True


def _is_no_such_key(err: ClientError) -> bool:
    code = err.response.get("Error", {}).get("Code")
    return (
        code in {"NoSuchKey", "404"}
        or err.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404
    )


__all__ = ["S3BlobStore"]

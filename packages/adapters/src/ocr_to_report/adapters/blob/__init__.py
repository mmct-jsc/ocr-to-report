"""Blob storage abstraction.

* :class:`BlobStore` — async protocol every backend implements.
* :class:`LocalBlobStore` — filesystem-backed (dev and tests).
* :class:`S3BlobStore` — S3-compatible via aioboto3 (MinIO, R2, S3 GCS).
"""

from ocr_to_report.adapters.blob.local import LocalBlobStore
from ocr_to_report.adapters.blob.protocol import (
    BlobMetadata,
    BlobNotFoundError,
    BlobStore,
    BlobStoreError,
)
from ocr_to_report.adapters.blob.s3 import S3BlobStore

__all__ = [
    "BlobMetadata",
    "BlobNotFoundError",
    "BlobStore",
    "BlobStoreError",
    "LocalBlobStore",
    "S3BlobStore",
]

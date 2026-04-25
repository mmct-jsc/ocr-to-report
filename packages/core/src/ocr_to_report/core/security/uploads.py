"""Magic-byte upload validation.

Defense in depth against polyglot files: even with strict server-side
size limits, a request that *says* it's a PNG but starts with a Java
class file (CAFEBABE) is suspicious. We sniff the leading bytes and
reject anything that isn't on the allowlist of media types we
actually process.

Detection priority:

1. Exact magic-byte prefix.
2. Returned media type is the canonical IANA name (e.g.,
   ``application/pdf`` not ``application/x-pdf``).

Tests live alongside ``preprocess`` in the adapters layer; the helper
is here in core because it has zero IO dependencies.
"""

from __future__ import annotations

from typing import Final

from ocr_to_report.core.errors.domain import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)

# Tuples of (canonical media type, magic prefix). Order matters when
# prefixes overlap (none currently do).
_MAGIC_BYTES: Final[tuple[tuple[str, bytes], ...]] = (
    ("application/pdf", b"%PDF-"),
    ("image/png", b"\x89PNG\r\n\x1a\n"),
    ("image/jpeg", b"\xff\xd8\xff"),
    ("image/gif", b"GIF87a"),
    ("image/gif", b"GIF89a"),
    ("image/webp", b"RIFF"),
    ("image/tiff", b"II*\x00"),
    ("image/tiff", b"MM\x00*"),
)


SUPPORTED_MEDIA_TYPES: Final[frozenset[str]] = frozenset(
    {media for media, _ in _MAGIC_BYTES}
)


def detect_media_type(blob: bytes) -> str | None:
    """Return the canonical IANA media type for ``blob`` or ``None``.

    Inspects the first 16 bytes; anything shorter is unknown.
    """
    if len(blob) < 4:
        return None
    head = blob[:16]
    for media, prefix in _MAGIC_BYTES:
        if not head.startswith(prefix):
            continue
        # WebP needs an additional WEBP marker at offset 8 — guard
        # against a false positive on bare RIFF (e.g., AVI).
        if media == "image/webp" and (len(blob) < 12 or blob[8:12] != b"WEBP"):
            continue
        return media
    return None


def require_safe_upload(blob: bytes, *, max_bytes: int) -> str:
    """Validate size + media type; return the detected media type.

    Args:
        blob: The raw upload bytes.
        max_bytes: Server-configured maximum size (from
            :class:`Settings.max_upload_bytes`).

    Returns:
        The canonical IANA media type.

    Raises:
        PayloadTooLargeError: ``len(blob) > max_bytes``.
        UnsupportedMediaTypeError: The blob's magic bytes don't match
            any supported type, or it's empty/too short to identify.
    """
    if len(blob) > max_bytes:
        raise PayloadTooLargeError(
            f"upload is {len(blob)} bytes; max is {max_bytes}",
            size=len(blob),
            max_bytes=max_bytes,
        )
    media = detect_media_type(blob)
    if media is None:
        raise UnsupportedMediaTypeError(
            "upload is not a recognized PDF or image type "
            "(supported: PDF, PNG, JPEG, GIF, WebP, TIFF)",
            size=len(blob),
        )
    return media


__all__ = [
    "SUPPORTED_MEDIA_TYPES",
    "detect_media_type",
    "require_safe_upload",
]

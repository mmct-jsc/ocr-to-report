"""Phase 11 — magic-byte upload validation."""

from __future__ import annotations

import io

import pytest
from PIL import Image as PILImage

from ocr_to_report.core.errors.domain import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
)
from ocr_to_report.core.security import (
    SUPPORTED_MEDIA_TYPES,
    detect_media_type,
    require_safe_upload,
)


def _png_bytes() -> bytes:
    img = PILImage.new("RGB", (4, 4), color=(0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def _jpeg_bytes() -> bytes:
    img = PILImage.new("RGB", (4, 4), color=(0, 0, 0))
    out = io.BytesIO()
    img.save(out, format="JPEG")
    return out.getvalue()


def test_detect_pdf() -> None:
    assert detect_media_type(b"%PDF-1.7\n...") == "application/pdf"


def test_detect_png() -> None:
    assert detect_media_type(_png_bytes()) == "image/png"


def test_detect_jpeg() -> None:
    assert detect_media_type(_jpeg_bytes()) == "image/jpeg"


def test_detect_gif() -> None:
    assert detect_media_type(b"GIF89a\x00\x00\x00\x00...") == "image/gif"


def test_detect_webp_with_marker() -> None:
    assert (
        detect_media_type(b"RIFF\x00\x00\x00\x00WEBP\x00\x00\x00\x00")
        == "image/webp"
    )


def test_riff_without_webp_marker_is_unknown() -> None:
    """Bare RIFF (e.g., AVI) is not a supported image."""
    assert detect_media_type(b"RIFF\x00\x00\x00\x00AVI \x00\x00\x00\x00") is None


def test_unknown_magic_returns_none() -> None:
    assert detect_media_type(b"CAFEBABE...") is None
    assert detect_media_type(b"") is None
    assert detect_media_type(b"abc") is None


def test_supported_media_types_set_contents() -> None:
    expected = {
        "application/pdf",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
        "image/tiff",
    }
    assert expected == SUPPORTED_MEDIA_TYPES


def test_require_safe_upload_returns_media_type_for_valid_png() -> None:
    media = require_safe_upload(_png_bytes(), max_bytes=10 * 1024)
    assert media == "image/png"


def test_require_safe_upload_rejects_oversize_blob() -> None:
    blob = b"%PDF-" + b"\x00" * (20)
    with pytest.raises(PayloadTooLargeError):
        require_safe_upload(blob, max_bytes=10)


def test_require_safe_upload_rejects_unknown_format() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        require_safe_upload(b"not a real image\x00\x00", max_bytes=1024)


def test_require_safe_upload_rejects_empty_blob() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        require_safe_upload(b"", max_bytes=1024)

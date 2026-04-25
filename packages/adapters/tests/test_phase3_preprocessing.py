"""Image preprocessing tests."""

from __future__ import annotations

import io
from collections.abc import Callable

import pytest
from PIL import Image as PILImage

from ocr_to_report.adapters.vision.preprocessing import (
    PreprocessConfig,
    detect_media_type,
    preprocess,
)
from ocr_to_report.core.errors.domain import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationError,
)

PngFactory = Callable[..., bytes]


# ─── Magic-byte detection ──────────────────────────────────────
def test_detect_png(png_bytes_factory: PngFactory) -> None:
    assert detect_media_type(png_bytes_factory()) == "image/png"


def test_detect_pdf() -> None:
    assert detect_media_type(b"%PDF-1.4\nrest of file") == "application/pdf"


def test_detect_jpeg() -> None:
    assert detect_media_type(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00") == "image/jpeg"


def test_detect_unknown_rejected() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        detect_media_type(b"not a real image format")


def test_detect_office_doc_rejected() -> None:
    # ZIP signature (docx/xlsx etc.) — must not be misidentified
    with pytest.raises(UnsupportedMediaTypeError):
        detect_media_type(b"PK\x03\x04...")


# ─── Preprocessing — image input ───────────────────────────────
def test_preprocess_returns_png_bytes(png_bytes_factory: PngFactory) -> None:
    blob = png_bytes_factory(size=(2400, 3000))
    pages = preprocess(blob)
    assert len(pages) == 1
    assert pages[0].startswith(b"\x89PNG\r\n\x1a\n")


def test_preprocess_resizes_oversized_image(png_bytes_factory: PngFactory) -> None:
    blob = png_bytes_factory(size=(4000, 6000))
    pages = preprocess(blob, PreprocessConfig(max_long_edge_px=1568))
    img = PILImage.open(io.BytesIO(pages[0]))
    assert max(img.size) <= 1568
    assert max(img.size) >= 1567


def test_preprocess_keeps_small_image_unchanged_size(png_bytes_factory: PngFactory) -> None:
    original_size = (800, 1000)
    blob = png_bytes_factory(size=original_size)
    pages = preprocess(blob, PreprocessConfig(max_long_edge_px=1568))
    img = PILImage.open(io.BytesIO(pages[0]))
    assert img.size == original_size


def test_preprocess_rejects_too_small(png_bytes_factory: PngFactory) -> None:
    blob = png_bytes_factory(size=(100, 100))
    with pytest.raises(ValidationError):
        preprocess(blob, PreprocessConfig(min_long_edge_px=200))


def test_preprocess_rejects_oversized_input(png_bytes_factory: PngFactory) -> None:
    blob = png_bytes_factory(size=(2000, 2000))
    cfg = PreprocessConfig(max_input_bytes=100)  # tiny limit forces reject
    with pytest.raises(PayloadTooLargeError):
        preprocess(blob, cfg)


def test_preprocess_strips_exif(png_bytes_factory: PngFactory) -> None:
    """Round-tripped output must contain no EXIF metadata."""
    blob = png_bytes_factory(size=(800, 1000))
    pages = preprocess(blob)
    img = PILImage.open(io.BytesIO(pages[0]))
    info_keys = set(img.info.keys()) if img.info else set()
    assert "exif" not in info_keys


def test_preprocess_unsupported_format_raises() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        preprocess(b"random bytes that match no magic")


def test_preprocess_max_pages_enforced(png_bytes_factory: PngFactory) -> None:
    """If somehow more pages slip through, validation rejects them.

    With image input we can only produce one page, so this also exercises
    the page-count validator's lower bound.
    """
    blob = png_bytes_factory(size=(800, 1000))
    pages = preprocess(blob, PreprocessConfig(max_pages=1))
    assert len(pages) == 1

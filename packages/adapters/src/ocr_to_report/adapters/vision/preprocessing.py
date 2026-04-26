"""Image preprocessing pipeline (Pillow + pdf2image).

What this does, in order:

1. **PDF → page images** (only if input is a PDF).
2. **EXIF strip** — remove all metadata (PII risk, irrelevant to extraction).
3. **Auto-orientation** — rotate by EXIF orientation tag before stripping.
4. **Auto-contrast** — Pillow's ImageOps.autocontrast for faded transcripts.
5. **Resize** — clamp the long edge to a configurable max (default 1568px;
   Anthropic's recommended high-quality cap for vision).
6. **Re-encode** as PNG — Pillow round-trips drop any embedded scripts /
   polyglots; PNG keeps text legible without JPEG artifacts.

Output: list of preprocessed PNG byte strings, one per page.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ocr_to_report.core.errors.domain import (
    PayloadTooLargeError,
    UnsupportedMediaTypeError,
    ValidationError,
)

if TYPE_CHECKING:
    from PIL.Image import Image

# Sane defaults; tenant SLA can override via PreprocessConfig.
DEFAULT_MAX_LONG_EDGE_PX: Final[int] = 1568
DEFAULT_MIN_LONG_EDGE_PX: Final[int] = 200
DEFAULT_MAX_PAGES: Final[int] = 10
DEFAULT_MAX_INPUT_BYTES: Final[int] = 25 * 1024 * 1024  # 25 MB
DEFAULT_PDF_RENDER_DPI: Final[int] = 150
"""150 DPI is plenty for OCR on a sub-1568px-long-edge target — and it
keeps a 2-page Polish transcript from spending 20+ seconds in
pdftocairo before we even talk to the model."""

_PDF_MAGIC: Final[bytes] = b"%PDF-"
_PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
_JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
_GIF_MAGIC: Final[tuple[bytes, ...]] = (b"GIF87a", b"GIF89a")
_TIFF_MAGIC: Final[tuple[bytes, ...]] = (b"II*\x00", b"MM\x00*")
_WEBP_MAGIC: Final[bytes] = b"RIFF"  # followed by 4 bytes then 'WEBP'


@dataclass(frozen=True, slots=True)
class PreprocessConfig:
    """Knobs for the preprocessing pipeline."""

    max_long_edge_px: int = DEFAULT_MAX_LONG_EDGE_PX
    min_long_edge_px: int = DEFAULT_MIN_LONG_EDGE_PX
    max_pages: int = DEFAULT_MAX_PAGES
    max_input_bytes: int = DEFAULT_MAX_INPUT_BYTES
    pdf_render_dpi: int = DEFAULT_PDF_RENDER_DPI
    autocontrast: bool = True


def detect_media_type(blob: bytes) -> str:
    """Identify supported input formats by magic bytes.

    Returns a MIME type. Raises :class:`UnsupportedMediaTypeError` for
    anything else (including office docs, archives, executables).
    """
    if blob.startswith(_PDF_MAGIC):
        return "application/pdf"
    if blob.startswith(_PNG_MAGIC):
        return "image/png"
    if blob.startswith(_JPEG_MAGIC):
        return "image/jpeg"
    if blob.startswith(_GIF_MAGIC):
        return "image/gif"
    if blob.startswith(_TIFF_MAGIC):
        return "image/tiff"
    if blob.startswith(_WEBP_MAGIC) and blob[8:12] == b"WEBP":
        return "image/webp"
    raise UnsupportedMediaTypeError(
        "input must be PDF, PNG, JPEG, GIF, TIFF, or WebP",
        observed_prefix=blob[:16].hex(),
    )


def preprocess(blob: bytes, config: PreprocessConfig | None = None) -> list[bytes]:
    """Preprocess any supported input into a list of clean PNG byte strings.

    PDF input → one PNG per page (up to ``max_pages``).
    Image input → one PNG (the input, scrubbed and resized).

    Raises:
        PayloadTooLargeError: if input exceeds ``max_input_bytes`` or page count.
        UnsupportedMediaTypeError: if magic bytes don't match a supported format.
        ValidationError: if a page is too small to be a useful transcript.
    """
    cfg = config or PreprocessConfig()
    if len(blob) > cfg.max_input_bytes:
        raise PayloadTooLargeError(
            f"input is {len(blob)} bytes; max is {cfg.max_input_bytes}",
            input_bytes=len(blob),
            max_bytes=cfg.max_input_bytes,
        )

    media_type = detect_media_type(blob)
    images = _pdf_to_images(blob, cfg) if media_type == "application/pdf" else [_load_image(blob)]

    if len(images) > cfg.max_pages:
        raise PayloadTooLargeError(
            f"input has {len(images)} pages; max is {cfg.max_pages}",
            page_count=len(images),
            max_pages=cfg.max_pages,
        )

    return [_clean_and_resize(img, cfg) for img in images]


def _pdf_to_images(blob: bytes, cfg: PreprocessConfig) -> list[Image]:
    # Imports done lazily so test-time stubs can still load without poppler.
    from pdf2image import convert_from_bytes  # noqa: PLC0415

    try:
        return list(
            convert_from_bytes(
                blob,
                dpi=cfg.pdf_render_dpi,
                fmt="png",
                last_page=cfg.max_pages,
                use_pdftocairo=True,
                # Render pages in parallel — single-threaded on a 2-page
                # transcript still takes ~10s with pdftocairo at 150 DPI.
                thread_count=2,
            )
        )
    except Exception as e:
        raise ValidationError(
            f"could not render PDF: {e}; ensure poppler-utils is installed",
        ) from e


def _load_image(blob: bytes) -> Image:
    from PIL import Image as PILImage  # noqa: PLC0415

    try:
        img = PILImage.open(io.BytesIO(blob))
        img.load()
    except Exception as e:
        raise ValidationError(f"could not decode image: {e}") from e
    return img


def _clean_and_resize(img: Image, cfg: PreprocessConfig) -> bytes:
    from PIL import Image as PILImage  # noqa: PLC0415
    from PIL import ImageOps  # noqa: PLC0415

    # 1. Auto-orient by EXIF orientation tag (must run before EXIF strip).
    img = ImageOps.exif_transpose(img)

    # 2. Strip EXIF + other metadata by reconstructing from pixel data.
    img = _strip_metadata(img)

    # 3. Convert to RGB (vision APIs reject CMYK and 1-bit modes).
    if img.mode not in {"RGB", "RGBA"}:
        img = img.convert("RGB")

    # 4. Auto-contrast for faded scans / low-contrast documents.
    if cfg.autocontrast:
        img = ImageOps.autocontrast(
            img.convert("RGB"),
            cutoff=1,  # tolerate 1% extreme pixels (handles stamps/marks)
        )

    # 5. Validate minimum dimensions and resize down to max long edge.
    long_edge = max(img.size)
    if long_edge < cfg.min_long_edge_px:
        raise ValidationError(
            f"image long edge is {long_edge}px; minimum {cfg.min_long_edge_px}px "
            "for legible extraction",
            long_edge_px=long_edge,
        )
    if long_edge > cfg.max_long_edge_px:
        scale = cfg.max_long_edge_px / long_edge
        new_size = (max(1, int(img.size[0] * scale)), max(1, int(img.size[1] * scale)))
        img = img.resize(new_size, PILImage.Resampling.LANCZOS)

    # 6. Re-encode as PNG without metadata.
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True, pnginfo=None)
    return out.getvalue()


def _strip_metadata(img: Image) -> Image:
    """Reconstruct the image from raw pixel bytes — drops every metadata
    chunk Pillow would otherwise round-trip (EXIF, IPTC, XMP, ICC, etc.)."""
    from PIL import Image as PILImage  # noqa: PLC0415

    return PILImage.frombytes(img.mode, img.size, img.tobytes())


__all__ = [
    "DEFAULT_MAX_INPUT_BYTES",
    "DEFAULT_MAX_LONG_EDGE_PX",
    "DEFAULT_MAX_PAGES",
    "DEFAULT_MIN_LONG_EDGE_PX",
    "PreprocessConfig",
    "detect_media_type",
    "preprocess",
]

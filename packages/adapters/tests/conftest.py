"""Shared adapters fixtures."""

from __future__ import annotations

import io
from typing import Any

import pytest

# Pillow is a hard dep; produce small test images on demand.
try:
    from PIL import Image as PILImage
except ImportError:  # pragma: no cover - skipped at import for environments without Pillow
    PILImage = None  # type: ignore[assignment]


@pytest.fixture
def png_bytes_factory() -> Any:
    """Return a callable that builds an in-memory PNG of the requested size."""

    def _make(
        size: tuple[int, int] = (800, 1200), color: tuple[int, int, int] = (240, 240, 200)
    ) -> bytes:
        if PILImage is None:
            pytest.skip("Pillow is required for image fixtures")
        img = PILImage.new("RGB", size, color)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()

    return _make

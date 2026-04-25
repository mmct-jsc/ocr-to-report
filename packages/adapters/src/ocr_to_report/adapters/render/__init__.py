"""Output renderers — fill target templates with render data.

The Excel renderer is the only one shipped in MVP. PDF/DOCX renderers
follow the same protocol and can be added without changes elsewhere.
"""

from ocr_to_report.adapters.render.protocol import RendererError, render
from ocr_to_report.adapters.render.xlsx_renderer import (
    XlsxRenderer,
    render_xlsx,
)

__all__ = ["RendererError", "XlsxRenderer", "render", "render_xlsx"]

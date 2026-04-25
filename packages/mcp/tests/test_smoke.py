"""Phase 0 smoke test."""

from ocr_to_report import mcp


def test_mcp_imports() -> None:
    assert mcp.__version__.startswith("0.1.0")

"""Phase 0 smoke test."""

from ocr_to_report import adapters


def test_adapters_imports() -> None:
    assert adapters.__version__.startswith("0.1.0")

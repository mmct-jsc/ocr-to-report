"""Phase 0 smoke test — confirms package importable and version exposed."""

from ocr_to_report import core


def test_core_imports() -> None:
    assert core.__version__.startswith("0.1.0")

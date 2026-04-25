"""Phase 0 smoke test."""

from ocr_to_report import worker


def test_worker_imports() -> None:
    assert worker.__version__.startswith("0.1.0")

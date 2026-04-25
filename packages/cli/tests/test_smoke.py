"""Phase 0 smoke test."""

from ocr_to_report import cli


def test_cli_imports() -> None:
    assert cli.__version__.startswith("0.1.0")

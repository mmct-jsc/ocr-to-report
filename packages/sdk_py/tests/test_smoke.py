"""Phase 0 smoke test."""

from ocr_to_report import sdk_py


def test_sdk_py_imports() -> None:
    assert sdk_py.__version__ == "0.2.0"

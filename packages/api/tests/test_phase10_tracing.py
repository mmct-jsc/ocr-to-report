"""Phase 10 — OTel tracing wiring.

We verify the contract: when no OTLP endpoint is configured, install
is a silent no-op (apps must boot without any observability stack
running). End-to-end span verification belongs in nightly E2E, not
unit scope.
"""

from __future__ import annotations

import pytest

from ocr_to_report.api.settings import Settings
from ocr_to_report.api.tracing import _resolve_sample_ratio, install_tracing


def test_install_tracing_is_noop_when_endpoint_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without OCR2R_OTLP_ENDPOINT or OTEL_EXPORTER_OTLP_ENDPOINT, no-op."""
    monkeypatch.delenv("OCR2R_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    # A bare object stands in for FastAPI; install_tracing must not touch it.
    fake_app = object()
    settings = Settings(env="development")
    # Must not raise, must not interact with the app.
    install_tracing(fake_app, settings)  # type: ignore[arg-type]


def test_resolve_sample_ratio_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCR2R_OTEL_SAMPLE_RATIO", raising=False)
    assert _resolve_sample_ratio() == pytest.approx(0.05)


def test_resolve_sample_ratio_clamped_to_unit_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR2R_OTEL_SAMPLE_RATIO", "1.5")
    assert _resolve_sample_ratio() == 1.0
    monkeypatch.setenv("OCR2R_OTEL_SAMPLE_RATIO", "-0.2")
    assert _resolve_sample_ratio() == 0.0


def test_resolve_sample_ratio_garbage_falls_back_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR2R_OTEL_SAMPLE_RATIO", "not-a-number")
    assert _resolve_sample_ratio() == pytest.approx(0.05)

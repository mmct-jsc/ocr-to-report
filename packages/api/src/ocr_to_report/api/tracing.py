"""OpenTelemetry tracing wiring.

Behavior:

* If ``OCR2R_OTLP_ENDPOINT`` (or the standard ``OTEL_EXPORTER_OTLP_ENDPOINT``)
  is unset, this is a no-op — useful for unit tests, dev, and any
  deployment that doesn't care about traces.
* When configured, sets up an OTLP/HTTP exporter, a parent-based
  ratio sampler (5% default; tunable via ``OCR2R_OTEL_SAMPLE_RATIO``),
  and instruments FastAPI + httpx so client + server spans appear
  end-to-end without per-call wiring.
* SQLAlchemy / Redis instrumentations stay opt-in (they're listed in
  the dep block but not wired in MVP — incremental cost when we
  switch to managed Postgres).

The 5% sample ratio + ``ParentBased`` policy means: 5% of root spans
are sampled, but every downstream span follows its parent's decision,
giving full traces for the requests we do keep.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBased, TraceIdRatioBased

if TYPE_CHECKING:
    from fastapi import FastAPI

    from ocr_to_report.api.settings import Settings


_DEFAULT_SAMPLE_RATIO = 0.05
"""5% of root spans sampled by default — design plan §Decision 7."""


def install_tracing(app: FastAPI, settings: Settings) -> None:
    """Install OTel tracing on the app.

    Idempotent: if OTLP endpoint is unset, returns silently. If a
    :class:`TracerProvider` is already installed (e.g., when this is
    called from both API + worker in the same process during tests),
    this skips the instrumentation step rather than registering twice.
    """
    endpoint = (
        os.environ.get("OCR2R_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    )
    if not endpoint:
        return

    sample_ratio = _resolve_sample_ratio()

    resource = Resource.create(
        {
            "service.name": "ocr-to-report-api",
            "service.version": "0.1.0-dev",
            "deployment.environment": settings.env,
        }
    )

    # Avoid double-installing if another part of the process already did it.
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        provider = current
    else:
        provider = TracerProvider(
            resource=resource,
            sampler=ParentBased(TraceIdRatioBased(sample_ratio)),
        )
        provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint))
        )
        trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)
    HTTPXClientInstrumentor().instrument(tracer_provider=provider)


def _resolve_sample_ratio() -> float:
    """Honor ``OCR2R_OTEL_SAMPLE_RATIO`` if set; clamp to [0, 1]."""
    raw = os.environ.get("OCR2R_OTEL_SAMPLE_RATIO")
    if raw is None:
        return _DEFAULT_SAMPLE_RATIO
    try:
        value = float(raw)
    except ValueError:
        return _DEFAULT_SAMPLE_RATIO
    return max(0.0, min(1.0, value))


__all__ = ["install_tracing"]

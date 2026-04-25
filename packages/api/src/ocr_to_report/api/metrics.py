"""Prometheus metrics + ``/metrics`` endpoint wiring.

Three tiers of metrics following the design plan:

* **Tier 1 — golden signals**: HTTP traffic + error rate + latency.
* **Tier 2 — pipeline**: per-step duration, vision confidence, tokens,
  $-cost, circuit-breaker state.
* **Tier 3 — business**: transcripts processed (per tenant / profile /
  target / SLA tier), manual-review queue depth, webhook deliveries,
  cache hits.

The collectors live on a single :class:`Metrics` namespace so call
sites stay terse (``state.metrics.http_requests.labels(...).inc()``).
A single global registry is owned by :func:`build_metrics`; every
process gets its own — fine for production where each replica is a
distinct scrape target.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import Any

    from fastapi import FastAPI, Response

    from ocr_to_report.api.settings import Settings

# Histogram buckets tuned to OCR-to-Report's expected request profile:
# fast control endpoints (~10ms) all the way up to a heavy sync extract
# call hitting Sonnet (~25s).
_HTTP_LATENCY_BUCKETS = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    25.0,
    60.0,
)

# Vision-confidence histogram is bucketed on [0, 1] with denser bins
# near the SLA thresholds (0.80 / 0.85 / 0.95) where parking decisions
# happen.
_CONFIDENCE_BUCKETS = (0.0, 0.5, 0.7, 0.8, 0.85, 0.9, 0.95, 0.98, 1.0)


@dataclass(slots=True)
class Metrics:
    """All Prometheus collectors used by the API + worker.

    Bundle so call sites pass a single object rather than reaching
    into a global. The collectors share one
    :class:`CollectorRegistry` so :func:`generate_latest` returns a
    coherent snapshot.
    """

    registry: CollectorRegistry

    # ─── Tier 1: golden signals ──────────────────────────────
    http_requests_total: Counter
    http_request_duration_seconds: Histogram
    http_errors_total: Counter

    # ─── Tier 2: pipeline ────────────────────────────────────
    pipeline_step_duration_seconds: Histogram
    vision_confidence: Histogram
    vision_tokens_total: Counter
    vision_usd_cost_total: Counter
    circuit_state: Gauge

    # ─── Tier 3: business ────────────────────────────────────
    transcripts_processed_total: Counter
    manual_reviews_pending: Gauge
    webhook_deliveries_total: Counter
    cache_hits_total: Counter
    cache_misses_total: Counter


def build_metrics() -> Metrics:
    """Construct a fresh :class:`Metrics` with its own registry."""
    registry = CollectorRegistry()

    return Metrics(
        registry=registry,
        # ─── Tier 1 ─────────────────────────────────────────
        http_requests_total=Counter(
            "ocr2r_http_requests_total",
            "Total HTTP requests received.",
            labelnames=("method", "route", "status"),
            registry=registry,
        ),
        http_request_duration_seconds=Histogram(
            "ocr2r_http_request_duration_seconds",
            "HTTP request handling time, end to end.",
            labelnames=("method", "route"),
            buckets=_HTTP_LATENCY_BUCKETS,
            registry=registry,
        ),
        http_errors_total=Counter(
            "ocr2r_http_errors_total",
            "HTTP responses with status >= 400.",
            labelnames=("method", "route", "status"),
            registry=registry,
        ),
        # ─── Tier 2 ─────────────────────────────────────────
        pipeline_step_duration_seconds=Histogram(
            "ocr2r_pipeline_step_duration_seconds",
            "Wall-clock time per pipeline step.",
            labelnames=("pipeline_id", "step_id"),
            buckets=_HTTP_LATENCY_BUCKETS,
            registry=registry,
        ),
        vision_confidence=Histogram(
            "ocr2r_vision_confidence",
            "Distribution of overall extraction confidence.",
            labelnames=("provider", "model"),
            buckets=_CONFIDENCE_BUCKETS,
            registry=registry,
        ),
        vision_tokens_total=Counter(
            "ocr2r_vision_tokens_total",
            "Vision provider tokens consumed.",
            labelnames=("provider", "model", "kind"),
            registry=registry,
        ),
        vision_usd_cost_total=Counter(
            "ocr2r_vision_usd_cost_total",
            "Vision provider USD cost.",
            labelnames=("provider", "model"),
            registry=registry,
        ),
        circuit_state=Gauge(
            "ocr2r_circuit_state",
            "Provider circuit state (0=closed, 1=half_open, 2=open).",
            labelnames=("provider",),
            registry=registry,
        ),
        # ─── Tier 3 ─────────────────────────────────────────
        transcripts_processed_total=Counter(
            "ocr2r_transcripts_processed_total",
            "Transcripts that completed successfully.",
            labelnames=("tenant", "profile", "target", "sla"),
            registry=registry,
        ),
        manual_reviews_pending=Gauge(
            "ocr2r_manual_reviews_pending",
            "Jobs currently parked for manual review.",
            labelnames=("tenant",),
            registry=registry,
        ),
        webhook_deliveries_total=Counter(
            "ocr2r_webhook_deliveries_total",
            "Outgoing webhook delivery attempts.",
            labelnames=("event", "outcome"),
            registry=registry,
        ),
        cache_hits_total=Counter(
            "ocr2r_cache_hits_total",
            "Cache hits.",
            labelnames=("cache",),
            registry=registry,
        ),
        cache_misses_total=Counter(
            "ocr2r_cache_misses_total",
            "Cache misses.",
            labelnames=("cache",),
            registry=registry,
        ),
    )


# ─── Middleware ──────────────────────────────────────────────
class PrometheusMiddleware:
    """ASGI middleware that records request count + latency.

    Excludes ``/metrics`` itself to avoid self-referential noise. Routes
    are taken from FastAPI's matched-route attribute when available;
    falls back to the raw path otherwise.
    """

    def __init__(self, app: Any, *, metrics: Metrics) -> None:
        self.app = app
        self.metrics = metrics

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path") or "")
        if path == "/metrics":
            await self.app(scope, receive, send)
            return

        method = str(scope.get("method") or "")
        start = time.monotonic()
        status_holder: dict[str, int] = {"status": 500}

        async def _wrapped_send(message: dict[str, Any]) -> None:
            if message.get("type") == "http.response.start":
                raw_status = message.get("status", 500)
                status_holder["status"] = int(raw_status) if raw_status is not None else 500
            await send(message)

        try:
            await self.app(scope, receive, _wrapped_send)
        finally:
            duration = time.monotonic() - start
            route = _route_from_scope(scope, path)
            status = str(status_holder["status"])
            self.metrics.http_requests_total.labels(method, route, status).inc()
            self.metrics.http_request_duration_seconds.labels(method, route).observe(duration)
            if status_holder["status"] >= 400:
                self.metrics.http_errors_total.labels(method, route, status).inc()


def _route_from_scope(scope: dict[str, Any], path: str) -> str:
    """Prefer FastAPI's compiled-route path so cardinality stays low."""
    route = scope.get("route")
    if route is not None and hasattr(route, "path"):
        return str(route.path)
    return path


# ─── /metrics endpoint ───────────────────────────────────────
def install_metrics(app: FastAPI, settings: Settings) -> Metrics:
    """Build the metrics, mount the ``/metrics`` endpoint, and add
    the request-recording middleware.

    Returns the :class:`Metrics` so callers can attach it to
    :class:`AppState` for use elsewhere.
    """
    metrics = build_metrics()
    app.state.metrics = metrics

    app.add_middleware(PrometheusMiddleware, metrics=metrics)

    @app.get(
        "/metrics",
        include_in_schema=False,
        tags=["system"],
    )
    async def metrics_endpoint() -> Response:
        from fastapi import Response  # noqa: PLC0415

        return Response(
            content=generate_latest(metrics.registry),
            media_type=CONTENT_TYPE_LATEST,
        )

    _ = settings  # reserved for future tunables (sample rate, exclusions)
    return metrics


__all__ = [
    "Metrics",
    "PrometheusMiddleware",
    "build_metrics",
    "install_metrics",
]

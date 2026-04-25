"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ocr_to_report.adapters.db import dispose_engines
from ocr_to_report.api.deps import build_app_state
from ocr_to_report.api.errors import install_exception_handlers
from ocr_to_report.api.metrics import install_metrics
from ocr_to_report.api.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from ocr_to_report.api.routers import (
    dsr_router,
    jobs_router,
    templates_router,
    transcripts_router,
    usage_router,
    webhooks_router,
)
from ocr_to_report.api.settings import Settings, load_settings
from ocr_to_report.api.tracing import install_tracing
from ocr_to_report.api.version import get_version_info

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

API_PREFIX: Final[str] = "/v1"


def _make_lifespan(settings: Settings) -> Any:
    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            app.state.app_state = build_app_state(settings)
        except Exception:
            # Allow the app to start with a degraded app_state (e.g., when
            # KEK is unset in dev). Endpoints that need it will surface a
            # clear error per request rather than crashing at boot.
            app.state.app_state = None
        try:
            yield
        finally:
            await dispose_engines()

    return _lifespan


def create_app(*, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(
        title="OCR-to-Report",
        version=get_version_info().api,
        description=(
            "Schema-driven multi-language transcript-to-report SaaS. "
            "Universal core, per-tenant SLA + workflow, multi-provider "
            "vision pipeline."
        ),
        lifespan=_make_lifespan(settings),
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RequestIdMiddleware)
    install_exception_handlers(app)
    install_metrics(app, settings)
    install_tracing(app, settings)

    app.include_router(transcripts_router)
    app.include_router(jobs_router)
    app.include_router(webhooks_router)
    app.include_router(usage_router)
    app.include_router(templates_router)
    app.include_router(dsr_router)

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get(f"{API_PREFIX}/ready", tags=["system"])
    async def ready() -> JSONResponse:
        state = getattr(app.state, "app_state", None)
        checks = {
            "app_state": "ready" if state is not None else "not_configured",
            "vision_providers": "not_configured" if state is None else "ready",
            "blob_store": "not_configured" if state is None else "ready",
        }
        return JSONResponse({"status": "ok", "checks": checks})

    @app.get(f"{API_PREFIX}/version", tags=["system"])
    async def version() -> JSONResponse:
        return JSONResponse(get_version_info().to_dict())

    return app


app = create_app()

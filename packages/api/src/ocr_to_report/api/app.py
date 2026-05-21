"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Final

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.formparsers import MultiPartParser

from ocr_to_report.adapters.db import Base, dispose_engines, get_engine
from ocr_to_report.api.deps import build_app_state
from ocr_to_report.api.errors import install_exception_handlers
from ocr_to_report.api.metrics import install_metrics
from ocr_to_report.api.middleware import RequestIdMiddleware, SecurityHeadersMiddleware
from ocr_to_report.api.routers import (
    admin_router,
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

        # Opt-in: create tables on boot. Lets a fresh dev volume self-heal
        # without an out-of-band ``ocr-to-report bootstrap`` run. Default
        # off — production schema changes must go through alembic.
        if settings.auto_migrate_on_boot:
            try:
                engine = get_engine(settings.database_url)
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
            except Exception as e:
                # Don't crash startup if migration fails — /v1/ready will
                # surface the issue and the operator can intervene. The
                # blanket catch is intentional: any failure here (network,
                # perms, schema conflict) must NOT prevent the app from
                # booting and serving /v1/health, /v1/ready.
                import structlog  # noqa: PLC0415 — lazy to avoid boot import cycle

                structlog.get_logger(__name__).warning(
                    "auto_migrate_on_boot failed; continuing without schema",
                    error=str(e),
                )

        try:
            yield
        finally:
            await dispose_engines()

    return _lifespan


def create_app(*, settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()

    # Starlette's MultiPartParser defaults to a 1 MiB cap per uploaded
    # part. That's smaller than any real transcript image — multi-page
    # PDFs render to 5-20 MB PNGs even after preprocess. Align it with
    # the size we already enforce ourselves (`require_safe_upload`),
    # so the request reaches our handler instead of dying at the
    # multipart parser with a generic 400.
    MultiPartParser.max_part_size = settings.max_upload_bytes

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

    # CORS: only installed when the operator explicitly opts in. Without
    # this, browser-based callers on a different origin (e.g. an SDK
    # consumer's webpage, or a separately-tunneled UI) hit a 405 on the
    # OPTIONS preflight because no handler exists for that method on the
    # target route. Same-origin deployments (web nginx proxies /api/*)
    # don't need CORS — leaving the lists empty preserves that posture.
    if settings.cors_allowed_origins or settings.cors_allowed_origin_regex:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins or [],
            allow_origin_regex=settings.cors_allowed_origin_regex,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=[
                "Authorization",
                "Content-Type",
                "Idempotency-Key",
                "X-Acting-Tenant-Id",
                "X-Request-Id",
            ],
            expose_headers=["X-Request-Id"],
            # Bearer auth lives in the Authorization header, not cookies,
            # so we don't need credentials and can therefore allow the
            # wildcard `*` form when an operator wants it.
            allow_credentials=False,
            max_age=600,
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
    app.include_router(admin_router)

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok"})

    @app.get(f"{API_PREFIX}/ready", tags=["system"])
    async def ready() -> JSONResponse:
        state = getattr(app.state, "app_state", None)
        # Cheap probe — does the schema exist? An empty DB is the most
        # common "looks alive but nothing works" failure mode, since
        # every authenticated endpoint reads ``api_keys``.
        db_status = await _check_database(settings.database_url)
        checks = {
            "app_state": "ready" if state is not None else "not_configured",
            "vision_providers": "not_configured" if state is None else "ready",
            "blob_store": "not_configured" if state is None else "ready",
            "database": db_status,
        }
        # 503 if any deep check is in a non-ready state. The "not_configured"
        # branches on app_state are dev-only and intentionally allowed to
        # report 200 — they don't indicate an unhealthy deployment, only
        # an unconfigured one.
        degraded = db_status != "ready"
        return JSONResponse(
            {"status": "degraded" if degraded else "ok", "checks": checks},
            status_code=503 if degraded else 200,
        )

    @app.get(f"{API_PREFIX}/version", tags=["system"])
    async def version() -> JSONResponse:
        return JSONResponse(get_version_info().to_dict())

    return app


async def _check_database(database_url: str) -> str:
    """Probe whether the schema exists. Returns one of:

    * ``"ready"``         — the ``api_keys`` table is queryable
    * ``"schema_missing"`` — DB reachable but tables aren't there
    * ``"unreachable"``    — couldn't connect at all

    Kept narrow on purpose; this is a /v1/ready signal, not a metrics
    surface. Detailed introspection lives in the metrics middleware.
    """
    try:
        engine = get_engine(database_url)
        async with engine.connect() as conn:
            # LIMIT 0 — we don't care about rows, only that the table
            # exists. The query is parsed + planned and returns
            # immediately without scanning.
            await conn.execute(text("SELECT 1 FROM api_keys LIMIT 0"))
        return "ready"
    except Exception as e:
        msg = str(e).lower()
        if "undefinedtable" in msg or "no such table" in msg or "does not exist" in msg:
            return "schema_missing"
        return "unreachable"


app = create_app()

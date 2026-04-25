"""FastAPI application factory.

Phase 0 surface: only liveness/readiness/version endpoints. Routers, auth,
middleware are introduced incrementally in Phases 5-6.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Final

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from ocr_to_report.api.version import get_version_info

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

API_PREFIX: Final[str] = "/v1"


@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Phase 0: no resources to initialize. Future phases will open DB/Redis/blob
    # connection pools here and close them on shutdown.
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="OCR-to-Report",
        version=get_version_info().api,
        description=(
            "Schema-driven multi-language transcript-to-report SaaS. "
            "Phase 0 surface: liveness/readiness/version only."
        ),
        lifespan=_lifespan,
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=f"{API_PREFIX}/redoc",
        openapi_url=f"{API_PREFIX}/openapi.json",
    )

    @app.get(f"{API_PREFIX}/health", tags=["system"])
    async def health() -> JSONResponse:
        """Liveness probe — answers iff the process is up."""
        return JSONResponse({"status": "ok"})

    @app.get(f"{API_PREFIX}/ready", tags=["system"])
    async def ready() -> JSONResponse:
        """Readiness probe.

        Phase 0: always ready (no external dependencies wired yet).
        Phase 5+ will deep-check DB/Redis/blob/≥1 vision provider.
        """
        return JSONResponse(
            {
                "status": "ok",
                "checks": {
                    "database": "not_configured",
                    "queue": "not_configured",
                    "blob_store": "not_configured",
                    "vision_providers": "not_configured",
                },
            }
        )

    @app.get(f"{API_PREFIX}/version", tags=["system"])
    async def version() -> JSONResponse:
        """Build/runtime version metadata."""
        return JSONResponse(get_version_info().to_dict())

    return app


app = create_app()

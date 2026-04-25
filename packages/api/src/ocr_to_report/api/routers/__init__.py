"""HTTP routers for the v1 API."""

from ocr_to_report.api.routers.dsr import router as dsr_router
from ocr_to_report.api.routers.jobs import router as jobs_router
from ocr_to_report.api.routers.templates import router as templates_router
from ocr_to_report.api.routers.transcripts import router as transcripts_router
from ocr_to_report.api.routers.usage import router as usage_router
from ocr_to_report.api.routers.webhooks import router as webhooks_router

__all__ = [
    "dsr_router",
    "jobs_router",
    "templates_router",
    "transcripts_router",
    "usage_router",
    "webhooks_router",
]

"""RFC 7807 problem-details exception handlers.

Every domain :class:`OcrToReportError` becomes an
``application/problem+json`` response with the right status code. The
handler also catches Pydantic validation errors and the FastAPI
``RequestValidationError`` so 4xx responses are uniform across hand-
crafted and framework-emitted errors.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ocr_to_report.core.errors.domain import (
    OcrToReportError,
    UnauthorizedError,
)
from ocr_to_report.core.errors.domain import (
    ValidationError as DomainValidationError,
)

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"


def install_exception_handlers(app: FastAPI) -> None:
    """Attach the exception handlers to a FastAPI app."""

    @app.exception_handler(OcrToReportError)
    async def _domain_handler(request: Request, exc: OcrToReportError) -> JSONResponse:
        return _to_problem_response(request, exc)

    @app.exception_handler(RequestValidationError)
    async def _request_validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        wrapped = DomainValidationError(
            "request validation failed",
            errors=[_format_pydantic_error(e) for e in exc.errors()],
        )
        return _to_problem_response(request, wrapped)

    @app.exception_handler(ValidationError)
    async def _pydantic_handler(
        request: Request,
        exc: ValidationError,
    ) -> JSONResponse:
        wrapped = DomainValidationError(
            "validation failed",
            errors=[_format_pydantic_error(dict(e)) for e in exc.errors()],
        )
        return _to_problem_response(request, wrapped)


def _to_problem_response(request: Request, exc: OcrToReportError) -> JSONResponse:
    instance = _request_id(request)
    problem = exc.to_problem_detail(instance=instance)
    if exc.status >= 500:
        logger.exception(
            "server error: %s", exc.detail or exc.title, extra={"request_id": instance}
        )
    else:
        logger.warning(
            "client error: %s %s -> %d",
            request.method,
            request.url.path,
            exc.status,
            extra={"request_id": instance, "error_type": exc.type_uri},
        )
    headers = {}
    if isinstance(exc, UnauthorizedError):
        headers["WWW-Authenticate"] = "Bearer"
    return JSONResponse(
        problem.to_problem_json(),
        status_code=exc.status,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=headers,
    )


def _request_id(request: Request) -> str:
    rid = request.headers.get("x-request-id") or getattr(request.state, "request_id", None)
    if rid:
        return f"urn:request:{rid}"
    return f"urn:request:{uuid.uuid4()}"


def _format_pydantic_error(err: dict[str, object]) -> dict[str, object]:
    """Strip non-serializable parts from a Pydantic error dict."""
    return {
        "loc": err.get("loc"),
        "msg": err.get("msg"),
        "type": err.get("type"),
    }


# Suppress unused-import warning — types referenced via Annotated.


__all__ = ["PROBLEM_CONTENT_TYPE", "install_exception_handlers"]

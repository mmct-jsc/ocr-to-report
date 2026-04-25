"""Per-request correlation id middleware.

Assigns a UUID4 to ``request.state.request_id`` for every request and
echoes it back as ``x-request-id`` on the response. Honors a caller-
supplied ``x-request-id`` header when present.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from starlette.requests import Request
    from starlette.responses import Response


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Ensures every request has a request id, available on
    ``request.state.request_id`` and echoed in the response."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response


__all__ = ["RequestIdMiddleware"]

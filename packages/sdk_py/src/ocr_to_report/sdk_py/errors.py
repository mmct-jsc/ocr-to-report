"""Typed exception hierarchy for SDK callers.

Every HTTP error from the API is mapped to one of these exceptions
based on the response's ``problem+json`` ``status`` (and ``type``). The
raw response body is preserved on the exception for callers that want
to introspect it (e.g., to read field-level validation errors).
"""

from __future__ import annotations

from typing import Any


class SDKError(Exception):
    """Base for every SDK exception.

    Attributes:
        status: HTTP status code from the response. ``None`` for
            transport-level errors (DNS, TLS, network).
        body: Decoded ``problem+json`` body, or ``None`` if the response
            wasn't JSON.
        request_id: The ``X-Request-Id`` header echoed back, when
            present. Useful when filing support tickets.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        body: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.body = body
        self.request_id = request_id


class BadRequestError(SDKError):
    """400 — validation or input shape problem."""


class AuthenticationError(SDKError):
    """401 — missing or invalid bearer token."""


class ForbiddenError(SDKError):
    """403 — authenticated but the operation is not allowed for this
    tenant (e.g., SLA tier disallows sync calls)."""


class NotFoundError(SDKError):
    """404 — job/template/webhook id not found."""


class ConflictError(SDKError):
    """409 — operation conflicts with current resource state (e.g.,
    approving a non-parked job)."""


class PayloadTooLargeError(SDKError):
    """413 — upload exceeds ``max_upload_bytes``."""


class RateLimitedError(SDKError):
    """429 — tenant rate limit exceeded."""


class ServerError(SDKError):
    """5xx — server-side error. Retry with exponential backoff."""


_STATUS_MAP: dict[int, type[SDKError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    403: ForbiddenError,
    404: NotFoundError,
    409: ConflictError,
    413: PayloadTooLargeError,
    429: RateLimitedError,
}


def from_response(
    *,
    status: int,
    body: dict[str, Any] | None,
    request_id: str | None,
) -> SDKError:
    """Build the right exception subclass for an HTTP error response."""
    cls = _STATUS_MAP.get(status, ServerError if status >= 500 else SDKError)
    detail = ""
    if body is not None:
        detail = str(body.get("detail") or body.get("title") or "")
    message = detail or f"HTTP {status}"
    return cls(message, status=status, body=body, request_id=request_id)


__all__ = [
    "AuthenticationError",
    "BadRequestError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "PayloadTooLargeError",
    "RateLimitedError",
    "SDKError",
    "ServerError",
    "from_response",
]

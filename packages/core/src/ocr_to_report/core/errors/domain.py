"""Domain-specific exception hierarchy.

Every error raised inside the core domain is one of these subclasses, each
carrying enough metadata to render an RFC 7807 :class:`ProblemDetail`.
Adapters and the API layer convert them; never raise raw built-ins (or
``Exception``) at module boundaries.
"""

from __future__ import annotations

from typing import Any

from ocr_to_report.core.errors.problem import ProblemDetail


class OcrToReportError(Exception):
    """Root of the domain exception hierarchy.

    Subclasses set class-level :attr:`status` and :attr:`type_uri` and may
    override :meth:`detail` for richer messages.
    """

    status: int = 500
    type_uri: str = "https://errors.ocr-to-report/internal"
    title: str = "Internal error"

    def __init__(self, detail: str | None = None, /, **extensions: Any) -> None:
        self._detail = detail
        self.extensions = dict(extensions)
        super().__init__(detail or self.title)

    @property
    def detail(self) -> str | None:
        return self._detail

    def to_problem_detail(self, *, instance: str | None = None) -> ProblemDetail:
        return ProblemDetail(
            type=self.type_uri,
            title=self.title,
            status=self.status,
            detail=self.detail,
            instance=instance,
            extensions=self.extensions,
        )


# ─── 4xx — client / input issues ───────────────────────────────
class ValidationError(OcrToReportError):
    status = 400
    type_uri = "https://errors.ocr-to-report/validation"
    title = "Validation failed"


class UnauthorizedError(OcrToReportError):
    status = 401
    type_uri = "https://errors.ocr-to-report/unauthorized"
    title = "Authentication required"


class ForbiddenError(OcrToReportError):
    status = 403
    type_uri = "https://errors.ocr-to-report/forbidden"
    title = "Operation not permitted"


class NotFoundError(OcrToReportError):
    status = 404
    type_uri = "https://errors.ocr-to-report/not-found"
    title = "Resource not found"


class ConflictError(OcrToReportError):
    status = 409
    type_uri = "https://errors.ocr-to-report/conflict"
    title = "Conflict"


class PayloadTooLargeError(OcrToReportError):
    status = 413
    type_uri = "https://errors.ocr-to-report/payload-too-large"
    title = "Payload too large"


class UnsupportedMediaTypeError(OcrToReportError):
    status = 415
    type_uri = "https://errors.ocr-to-report/unsupported-media-type"
    title = "Unsupported media type"


class TooManyRequestsError(OcrToReportError):
    status = 429
    type_uri = "https://errors.ocr-to-report/rate-limited"
    title = "Rate limit exceeded"


# ─── Domain-specific (4xx flavor) ──────────────────────────────
class ProfileNotFoundError(NotFoundError):
    type_uri = "https://errors.ocr-to-report/profile-not-found"
    title = "Profile not found"


class TargetNotFoundError(NotFoundError):
    type_uri = "https://errors.ocr-to-report/target-not-found"
    title = "Target system not found"


class TemplateNotFoundError(NotFoundError):
    type_uri = "https://errors.ocr-to-report/template-not-found"
    title = "Template not found"


class PipelineNotFoundError(NotFoundError):
    type_uri = "https://errors.ocr-to-report/pipeline-not-found"
    title = "Pipeline not found"


class ProfileFingerprintMismatchError(ValidationError):
    type_uri = "https://errors.ocr-to-report/profile-fingerprint-mismatch"
    title = "Document does not match the requested profile"


class MappingError(ValidationError):
    type_uri = "https://errors.ocr-to-report/mapping-failed"
    title = "Mapping failed"


class LowConfidenceError(ValidationError):
    type_uri = "https://errors.ocr-to-report/low-confidence"
    title = "Extraction confidence below threshold"


# ─── 5xx — server / dependency issues ──────────────────────────
class DependencyError(OcrToReportError):
    status = 502
    type_uri = "https://errors.ocr-to-report/dependency-failed"
    title = "Upstream dependency failed"


class VisionProviderError(DependencyError):
    type_uri = "https://errors.ocr-to-report/vision-provider-error"
    title = "Vision provider error"


class ProviderNotConfiguredError(OcrToReportError):
    """No vision provider with a real implementation is configured.

    Surfaces when the only adapter installed is one of the scaffolded
    stubs (e.g., when ``ANTHROPIC_API_KEY`` is unset in dev). Status
    503 so callers know to wait + retry rather than re-shape the
    request.
    """

    status = 503
    type_uri = "https://errors.ocr-to-report/provider-not-configured"
    title = "No vision provider configured"


class StorageError(DependencyError):
    type_uri = "https://errors.ocr-to-report/storage-error"
    title = "Storage backend error"


class OperationTimeoutError(OcrToReportError):
    """Operation exceeded its timeout. Named *OperationTimeoutError* (not
    *TimeoutError*) to avoid clashing with the built-in
    :class:`TimeoutError`."""

    status = 504
    type_uri = "https://errors.ocr-to-report/timeout"
    title = "Operation timed out"


class CircuitOpenError(DependencyError):
    status = 503
    type_uri = "https://errors.ocr-to-report/circuit-open"
    title = "Provider circuit breaker is open"


__all__ = [
    "CircuitOpenError",
    "ConflictError",
    "DependencyError",
    "ForbiddenError",
    "LowConfidenceError",
    "MappingError",
    "NotFoundError",
    "OcrToReportError",
    "OperationTimeoutError",
    "PayloadTooLargeError",
    "PipelineNotFoundError",
    "ProfileFingerprintMismatchError",
    "ProfileNotFoundError",
    "ProviderNotConfiguredError",
    "StorageError",
    "TargetNotFoundError",
    "TemplateNotFoundError",
    "TooManyRequestsError",
    "UnauthorizedError",
    "UnsupportedMediaTypeError",
    "ValidationError",
    "VisionProviderError",
]

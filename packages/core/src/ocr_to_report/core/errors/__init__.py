"""Error types for the core domain.

* :class:`ProblemDetail` — RFC 7807 envelope.
* :class:`OcrToReportError` and subclasses — domain exception hierarchy.

Every exception raised inside the domain is a subclass of
:class:`OcrToReportError`. Adapters convert third-party exceptions into
domain errors at the boundary.
"""

from ocr_to_report.core.errors.domain import (
    CircuitOpenError,
    ConflictError,
    DependencyError,
    ForbiddenError,
    LowConfidenceError,
    MappingError,
    NotFoundError,
    OcrToReportError,
    OperationTimeoutError,
    PayloadTooLargeError,
    PipelineNotFoundError,
    ProfileFingerprintMismatchError,
    ProfileNotFoundError,
    StorageError,
    TargetNotFoundError,
    TemplateNotFoundError,
    TooManyRequestsError,
    UnauthorizedError,
    UnsupportedMediaTypeError,
    ValidationError,
    VisionProviderError,
)
from ocr_to_report.core.errors.problem import ProblemDetail

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
    "ProblemDetail",
    "ProfileFingerprintMismatchError",
    "ProfileNotFoundError",
    "StorageError",
    "TargetNotFoundError",
    "TemplateNotFoundError",
    "TooManyRequestsError",
    "UnauthorizedError",
    "UnsupportedMediaTypeError",
    "ValidationError",
    "VisionProviderError",
]

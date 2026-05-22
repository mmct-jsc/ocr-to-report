"""OCR-to-Report public Python SDK.

HTTP client for the REST API. Never imports server-side code
(api / adapters / worker) — enforced by import-linter — so this package
can be installed in environments that don't have the server stack.

Public surface:

* :class:`Client` — synchronous HTTP client.
* :class:`AsyncClient` — asyncio-native HTTP client (same operations).
* :class:`SDKError` — base exception; subclasses for specific HTTP
  problem-detail types (auth, validation, not-found, etc.).
* :mod:`ocr_to_report.sdk_py.models` — Pydantic response models.

Quick start (sync):

    >>> from ocr_to_report.sdk_py import Client
    >>> client = Client(base_url="https://api.example.com", api_key="sk_...")
    >>> resp = client.transcripts.create(
    ...     file_bytes=open("transcript.pdf", "rb").read(),
    ...     filename="transcript.pdf",
    ...     profile_id="pl.lo.swiadectwo_szkolne.v1",
    ...     target_id="us-hs.v1",
    ... )
    >>> print(resp.job.status, resp.overall_confidence)
"""

from ocr_to_report.sdk_py.client import AsyncClient, Client
from ocr_to_report.sdk_py.errors import (
    AuthenticationError,
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    PayloadTooLargeError,
    RateLimitedError,
    SDKError,
    ServerError,
)
from ocr_to_report.sdk_py.models import (
    BatchAcceptedResponse,
    CustomTemplateResponse,
    JobSummary,
    TemplateInfo,
    TemplatesResponse,
    TenantConfigResponse,
    TenantConfigUpdate,
    TranscriptExtractionResponse,
    UsageResponse,
    WebhookCreateResponse,
    WebhookSummary,
)

__all__ = [
    "AsyncClient",
    "AuthenticationError",
    "BadRequestError",
    "BatchAcceptedResponse",
    "Client",
    "ConflictError",
    "CustomTemplateResponse",
    "ForbiddenError",
    "JobSummary",
    "NotFoundError",
    "PayloadTooLargeError",
    "RateLimitedError",
    "SDKError",
    "ServerError",
    "TemplateInfo",
    "TemplatesResponse",
    "TenantConfigResponse",
    "TenantConfigUpdate",
    "TranscriptExtractionResponse",
    "UsageResponse",
    "WebhookCreateResponse",
    "WebhookSummary",
]
__version__ = "0.3.0"

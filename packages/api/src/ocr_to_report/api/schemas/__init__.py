"""Request/response schemas."""

from ocr_to_report.api.schemas.admin import (
    ApiKeyIssueRequest,
    ApiKeyIssueResponse,
    ApiKeySummary,
    AuditEntrySummary,
    SystemOverview,
    TenantCreateRequest,
    TenantSummary,
    TenantUpdateRequest,
)
from ocr_to_report.api.schemas.dsr import (
    DSRAccessResponse,
    DSRErasureRequest,
    DSRErasureResponse,
    DSRPortabilityResponse,
)
from ocr_to_report.api.schemas.providers import (
    ProviderId,
    ProvidersListResponse,
    ProviderStatus,
    ProviderUpsertRequest,
)
from ocr_to_report.api.schemas.templates import CustomTemplateResponse
from ocr_to_report.api.schemas.tenant_config import (
    TenantConfigResponse,
    TenantConfigUpdate,
)
from ocr_to_report.api.schemas.transcripts import (
    BatchAcceptedResponse,
    TranscriptExtractionResponse,
    TranscriptJobSummary,
)
from ocr_to_report.api.schemas.usage import UsageResponse
from ocr_to_report.api.schemas.webhooks import (
    WebhookCreateRequest,
    WebhookCreateResponse,
    WebhookSummary,
)

__all__ = [
    "ApiKeyIssueRequest",
    "ApiKeyIssueResponse",
    "ApiKeySummary",
    "AuditEntrySummary",
    "BatchAcceptedResponse",
    "CustomTemplateResponse",
    "DSRAccessResponse",
    "DSRErasureRequest",
    "DSRErasureResponse",
    "DSRPortabilityResponse",
    "ProviderId",
    "ProviderStatus",
    "ProviderUpsertRequest",
    "ProvidersListResponse",
    "SystemOverview",
    "TenantConfigResponse",
    "TenantConfigUpdate",
    "TenantCreateRequest",
    "TenantSummary",
    "TenantUpdateRequest",
    "TranscriptExtractionResponse",
    "TranscriptJobSummary",
    "UsageResponse",
    "WebhookCreateRequest",
    "WebhookCreateResponse",
    "WebhookSummary",
]

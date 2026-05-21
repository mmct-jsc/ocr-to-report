"""Sync + async HTTP clients for the OCR-to-Report REST API.

Both clients share the same operation surface and Pydantic response
models; only the I/O is different. Internally each delegates to a
private ``_call`` that handles auth, problem-detail unwrapping, and
typed-error mapping so the per-operation methods stay terse.

Resource namespaces:

* :class:`Client.transcripts` — ``POST /v1/transcripts`` (sync extract)
  and ``POST /v1/transcripts:batch`` (async batch).
* :class:`Client.jobs` — get, list, approve, reject, fetch result blob.
* :class:`Client.webhooks` — create, list.
* :class:`Client.usage` — get current-period rollup.
* :class:`Client.templates` — list available targets/templates.

Same surface for :class:`AsyncClient`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any

import httpx

from ocr_to_report.sdk_py import errors
from ocr_to_report.sdk_py.models import (
    BatchAcceptedResponse,
    CustomTemplateResponse,
    JobSummary,
    ProviderId,
    ProvidersListResponse,
    ProviderStatus,
    ProviderUpsertRequest,
    TemplatesResponse,
    TenantConfigResponse,
    TenantConfigUpdate,
    TranscriptExtractionResponse,
    UsageResponse,
    WebhookCreateResponse,
    WebhookSummary,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

_DEFAULT_TIMEOUT_SECONDS = 60.0


# ─── Shared helpers ──────────────────────────────────────────
def _build_headers(api_key: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "User-Agent": "ocr-to-report-py/0.1"}
    if extra:
        headers.update(extra)
    return headers


def _raise_for_response(response: httpx.Response) -> None:
    """If ``response`` is a problem-detail error, raise the typed SDK exception."""
    if response.is_success:
        return
    body: dict[str, Any] | None = None
    try:
        if response.headers.get("content-type", "").startswith("application/"):
            body = response.json()
    except (ValueError, httpx.DecodingError):
        body = None
    request_id = response.headers.get("x-request-id")
    raise errors.from_response(status=response.status_code, body=body, request_id=request_id)


# ─── Sync client ─────────────────────────────────────────────
class Client:
    """Synchronous HTTP client.

    Args:
        base_url: API base URL (without trailing slash).
        api_key: Bearer token issued by the server (e.g., ``sk_live_...``).
        timeout_seconds: Per-request timeout. Defaults to 60s; bump for
            large batch uploads.
        http_client: Optional :class:`httpx.Client` for callers that
            already manage one (testing, custom transports). When
            supplied, the SDK won't close it on :meth:`close`.
    """

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owned_http = http_client is None
        self._http = http_client or httpx.Client(timeout=timeout_seconds)

        self.transcripts = TranscriptsResource(self)
        self.jobs = JobsResource(self)
        self.webhooks = WebhooksResource(self)
        self.usage = UsageResource(self)
        self.templates = TemplatesResource(self)
        self.tenant_config = TenantConfigResource(self)
        self.providers = ProvidersResource(self)

    def __enter__(self) -> Client:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owned_http:
            self._http.close()

    def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = _build_headers(self._api_key, extra_headers)
        response = self._http.request(
            method,
            url,
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            params=params,
        )
        _raise_for_response(response)
        return response


# ─── Async client ────────────────────────────────────────────
class AsyncClient:
    """asyncio-native HTTP client. Same surface as :class:`Client`."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._owned_http = http_client is None
        self._http = http_client or httpx.AsyncClient(timeout=timeout_seconds)

        self.transcripts = AsyncTranscriptsResource(self)
        self.jobs = AsyncJobsResource(self)
        self.webhooks = AsyncWebhooksResource(self)
        self.usage = AsyncUsageResource(self)
        self.templates = AsyncTemplatesResource(self)
        self.tenant_config = AsyncTenantConfigResource(self)
        self.providers = AsyncProvidersResource(self)

    async def __aenter__(self) -> AsyncClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owned_http:
            await self._http.aclose()

    async def _call(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
        params: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        url = f"{self._base_url}{path}"
        headers = _build_headers(self._api_key, extra_headers)
        response = await self._http.request(
            method,
            url,
            headers=headers,
            json=json_body,
            data=data,
            files=files,
            params=params,
        )
        _raise_for_response(response)
        return response


# ─── Sync resources ──────────────────────────────────────────
class TranscriptsResource:
    """``/v1/transcripts`` operations."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def create(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
        idempotency_key: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> TranscriptExtractionResponse:
        """POST /v1/transcripts (sync extract + render)."""
        data: dict[str, Any] = {"profile_id": profile_id, "target_id": target_id}
        if target_template_key is not None:
            data["target_template_key"] = target_template_key
        files = [("file", (filename, file_bytes, content_type))]
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = self._client._call(
            "POST",
            "/v1/transcripts",
            data=data,
            files=files,
            extra_headers=headers,
        )
        return TranscriptExtractionResponse.model_validate(response.json())

    def create_batch(
        self,
        *,
        files: Iterable[tuple[str, bytes, str]],
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
    ) -> BatchAcceptedResponse:
        """POST /v1/transcripts:batch (async batch ingestion)."""
        data: dict[str, Any] = {"profile_id": profile_id, "target_id": target_id}
        if target_template_key is not None:
            data["target_template_key"] = target_template_key
        files_payload = [
            ("files", (filename, blob, content_type)) for filename, blob, content_type in files
        ]
        if not files_payload:
            raise ValueError("at least one file is required")
        response = self._client._call(
            "POST",
            "/v1/transcripts:batch",
            data=data,
            files=files_payload,
        )
        return BatchAcceptedResponse.model_validate(response.json())


class JobsResource:
    """``/v1/jobs`` operations."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self, job_id: uuid.UUID | str) -> JobSummary:
        response = self._client._call("GET", f"/v1/jobs/{job_id}")
        return JobSummary.model_validate(response.json())

    def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[JobSummary]:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        response = self._client._call("GET", "/v1/jobs", params=params)
        return [JobSummary.model_validate(j) for j in response.json()]

    def get_result(self, job_id: uuid.UUID | str) -> bytes:
        """Download the rendered xlsx blob for a job."""
        response = self._client._call("GET", f"/v1/jobs/{job_id}/result")
        return response.content

    def approve(self, job_id: uuid.UUID | str) -> JobSummary:
        response = self._client._call("POST", f"/v1/jobs/{job_id}/approve")
        return JobSummary.model_validate(response.json())

    def reject(
        self,
        job_id: uuid.UUID | str,
        *,
        reason: str | None = None,
    ) -> JobSummary:
        body = {"reason": reason} if reason else {}
        response = self._client._call(
            "POST",
            f"/v1/jobs/{job_id}/reject",
            json_body=body,
        )
        return JobSummary.model_validate(response.json())


class WebhooksResource:
    def __init__(self, client: Client) -> None:
        self._client = client

    def create(self, *, url: str, events: list[str]) -> WebhookCreateResponse:
        response = self._client._call(
            "POST",
            "/v1/webhooks",
            json_body={"url": url, "events": events},
        )
        return WebhookCreateResponse.model_validate(response.json())

    def list(self) -> list[WebhookSummary]:
        response = self._client._call("GET", "/v1/webhooks")
        return [WebhookSummary.model_validate(w) for w in response.json()]


class UsageResource:
    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self) -> UsageResponse:
        response = self._client._call("GET", "/v1/usage")
        return UsageResponse.model_validate(response.json())


class TemplatesResource:
    def __init__(self, client: Client) -> None:
        self._client = client

    def list(self) -> TemplatesResponse:
        response = self._client._call("GET", "/v1/templates")
        return TemplatesResponse.model_validate(response.json())

    def upload(
        self,
        *,
        target_id: str,
        template_key: str,
        file_bytes: bytes,
        filename: str = "template.xlsx",
    ) -> CustomTemplateResponse:
        """Upload a tenant-specific xlsx that replaces the shipped template.

        The server validates magic bytes (``PK\\x03\\x04`` ZIP header) and
        runs ``openpyxl.load_workbook`` round-trip; anything that fails
        either check raises a typed SDK error.
        """
        files = [
            (
                "template_file",
                (
                    filename,
                    file_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ]
        response = self._client._call(
            "POST",
            f"/v1/templates/{target_id}/{template_key}",
            files=files,
        )
        return CustomTemplateResponse.model_validate(response.json())

    def delete(self, *, target_id: str, template_key: str) -> None:
        """Remove the tenant's custom template; revert to the shipped one.

        Returns nothing on success (204). Raises ``NotFoundError`` if no
        override exists for the slot.
        """
        self._client._call("DELETE", f"/v1/templates/{target_id}/{template_key}")


class TenantConfigResource:
    """``/v1/tenant/config`` — per-tenant override CRUD."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def get(self) -> TenantConfigResponse:
        response = self._client._call("GET", "/v1/tenant/config")
        return TenantConfigResponse.model_validate(response.json())

    def preview(self, body: TenantConfigUpdate) -> TenantConfigResponse:
        """Apply ``body`` against the current config WITHOUT persisting."""
        response = self._client._call(
            "POST",
            "/v1/tenant/config:preview",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return TenantConfigResponse.model_validate(response.json())

    def replace(self, body: TenantConfigUpdate) -> TenantConfigResponse:
        """Persist ``body``. Returns the resolved view after writes."""
        response = self._client._call(
            "PUT",
            "/v1/tenant/config",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return TenantConfigResponse.model_validate(response.json())


class ProvidersResource:
    """``/v1/tenant/providers`` — per-tenant BYOK credentials (v0.3.0).

    The server never echoes the plaintext key back: list responses use a
    fixed placeholder, the PUT response carries a last-4 redaction only.
    """

    def __init__(self, client: Client) -> None:
        self._client = client

    def list(self) -> ProvidersListResponse:
        response = self._client._call("GET", "/v1/tenant/providers")
        return ProvidersListResponse.model_validate(response.json())

    def upsert(self, provider: ProviderId, body: ProviderUpsertRequest) -> ProviderStatus:
        """Upsert + validate. Server runs a /v1/models probe against the
        candidate key before persisting; a bad key surfaces as a 400."""
        response = self._client._call(
            "PUT",
            f"/v1/tenant/providers/{provider}",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return ProviderStatus.model_validate(response.json())

    def delete(self, provider: ProviderId) -> None:
        """Soft-disable. Idempotent (204 even when no active row)."""
        self._client._call("DELETE", f"/v1/tenant/providers/{provider}")


# ─── Async resources (mirror the sync ones) ──────────────────
class AsyncTranscriptsResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def create(
        self,
        *,
        file_bytes: bytes,
        filename: str,
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
        idempotency_key: str | None = None,
        content_type: str = "application/octet-stream",
    ) -> TranscriptExtractionResponse:
        data: dict[str, Any] = {"profile_id": profile_id, "target_id": target_id}
        if target_template_key is not None:
            data["target_template_key"] = target_template_key
        files = [("file", (filename, file_bytes, content_type))]
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        response = await self._client._call(
            "POST",
            "/v1/transcripts",
            data=data,
            files=files,
            extra_headers=headers,
        )
        return TranscriptExtractionResponse.model_validate(response.json())

    async def create_batch(
        self,
        *,
        files: Iterable[tuple[str, bytes, str]],
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
    ) -> BatchAcceptedResponse:
        data: dict[str, Any] = {"profile_id": profile_id, "target_id": target_id}
        if target_template_key is not None:
            data["target_template_key"] = target_template_key
        files_payload = [
            ("files", (filename, blob, content_type)) for filename, blob, content_type in files
        ]
        if not files_payload:
            raise ValueError("at least one file is required")
        response = await self._client._call(
            "POST",
            "/v1/transcripts:batch",
            data=data,
            files=files_payload,
        )
        return BatchAcceptedResponse.model_validate(response.json())


class AsyncJobsResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def get(self, job_id: uuid.UUID | str) -> JobSummary:
        response = await self._client._call("GET", f"/v1/jobs/{job_id}")
        return JobSummary.model_validate(response.json())

    async def list(
        self,
        *,
        status: str | None = None,
        limit: int = 100,
    ) -> list[JobSummary]:
        params: dict[str, Any] = {"limit": limit}
        if status is not None:
            params["status"] = status
        response = await self._client._call("GET", "/v1/jobs", params=params)
        return [JobSummary.model_validate(j) for j in response.json()]

    async def get_result(self, job_id: uuid.UUID | str) -> bytes:
        response = await self._client._call("GET", f"/v1/jobs/{job_id}/result")
        return response.content

    async def approve(self, job_id: uuid.UUID | str) -> JobSummary:
        response = await self._client._call("POST", f"/v1/jobs/{job_id}/approve")
        return JobSummary.model_validate(response.json())

    async def reject(
        self,
        job_id: uuid.UUID | str,
        *,
        reason: str | None = None,
    ) -> JobSummary:
        body = {"reason": reason} if reason else {}
        response = await self._client._call(
            "POST",
            f"/v1/jobs/{job_id}/reject",
            json_body=body,
        )
        return JobSummary.model_validate(response.json())


class AsyncWebhooksResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def create(self, *, url: str, events: list[str]) -> WebhookCreateResponse:
        response = await self._client._call(
            "POST",
            "/v1/webhooks",
            json_body={"url": url, "events": events},
        )
        return WebhookCreateResponse.model_validate(response.json())

    async def list(self) -> list[WebhookSummary]:
        response = await self._client._call("GET", "/v1/webhooks")
        return [WebhookSummary.model_validate(w) for w in response.json()]


class AsyncUsageResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def get(self) -> UsageResponse:
        response = await self._client._call("GET", "/v1/usage")
        return UsageResponse.model_validate(response.json())


class AsyncTemplatesResource:
    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(self) -> TemplatesResponse:
        response = await self._client._call("GET", "/v1/templates")
        return TemplatesResponse.model_validate(response.json())

    async def upload(
        self,
        *,
        target_id: str,
        template_key: str,
        file_bytes: bytes,
        filename: str = "template.xlsx",
    ) -> CustomTemplateResponse:
        files = [
            (
                "template_file",
                (
                    filename,
                    file_bytes,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ),
            )
        ]
        response = await self._client._call(
            "POST",
            f"/v1/templates/{target_id}/{template_key}",
            files=files,
        )
        return CustomTemplateResponse.model_validate(response.json())

    async def delete(self, *, target_id: str, template_key: str) -> None:
        await self._client._call("DELETE", f"/v1/templates/{target_id}/{template_key}")


class AsyncTenantConfigResource:
    """Async variant of :class:`TenantConfigResource`."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def get(self) -> TenantConfigResponse:
        response = await self._client._call("GET", "/v1/tenant/config")
        return TenantConfigResponse.model_validate(response.json())

    async def preview(self, body: TenantConfigUpdate) -> TenantConfigResponse:
        response = await self._client._call(
            "POST",
            "/v1/tenant/config:preview",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return TenantConfigResponse.model_validate(response.json())

    async def replace(self, body: TenantConfigUpdate) -> TenantConfigResponse:
        response = await self._client._call(
            "PUT",
            "/v1/tenant/config",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return TenantConfigResponse.model_validate(response.json())


class AsyncProvidersResource:
    """Async variant of :class:`ProvidersResource`."""

    def __init__(self, client: AsyncClient) -> None:
        self._client = client

    async def list(self) -> ProvidersListResponse:
        response = await self._client._call("GET", "/v1/tenant/providers")
        return ProvidersListResponse.model_validate(response.json())

    async def upsert(self, provider: ProviderId, body: ProviderUpsertRequest) -> ProviderStatus:
        response = await self._client._call(
            "PUT",
            f"/v1/tenant/providers/{provider}",
            json_body=body.model_dump(mode="json", exclude_none=True),
        )
        return ProviderStatus.model_validate(response.json())

    async def delete(self, provider: ProviderId) -> None:
        await self._client._call("DELETE", f"/v1/tenant/providers/{provider}")


__all__ = [
    "AsyncClient",
    "AsyncJobsResource",
    "AsyncProvidersResource",
    "AsyncTemplatesResource",
    "AsyncTenantConfigResource",
    "AsyncTranscriptsResource",
    "AsyncUsageResource",
    "AsyncWebhooksResource",
    "Client",
    "JobsResource",
    "ProvidersResource",
    "TemplatesResource",
    "TenantConfigResource",
    "TranscriptsResource",
    "UsageResource",
    "WebhooksResource",
]

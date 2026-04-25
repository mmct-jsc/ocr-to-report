"""FastAPI dependency wiring.

Centralizes construction of the long-lived adapters (encryptor, blob
store, registries, vision router, renderer, etc.) and per-request
helpers (current tenant, current api_key, db session).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from ocr_to_report.adapters.blob import BlobStore, LocalBlobStore, S3BlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.db import (
    ApiKey,
    Tenant,
    dispose_engines,
    get_sessionmaker,
    tenant_scoped_session,
)
from ocr_to_report.adapters.db.repositories import (
    ApiKeyRepo,
    AuditRepo,
    BatchSubmissionRepo,
    IdempotencyRepo,
    JobRepo,
    TenantRepo,
    TranscriptRepo,
    UsageRepo,
    WebhookRepo,
)
from ocr_to_report.adapters.queue import InMemoryQueue, Queue
from ocr_to_report.adapters.render import XlsxRenderer
from ocr_to_report.adapters.vision import (
    AdaptivePolicy,
    AnthropicVisionAdapter,
    InMemoryAsyncCache,
    ProviderRouter,
    VisionProvider,
    compile_schema,
)
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.errors.domain import UnauthorizedError
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import (
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    load_presets_from_dir,
)
from ocr_to_report.core.targets import TargetRegistry


@dataclass(slots=True)
class AppState:
    """Long-lived adapter handles attached to ``app.state``."""

    settings: Settings
    encryptor: EnvelopeEncryptor
    profile_registry: ProfileRegistry
    target_registry: TargetRegistry
    blob_store: BlobStore
    vision_router: ProviderRouter
    result_cache: InMemoryAsyncCache
    bundle_roots: dict[str, Path]
    """Maps target_id → absolute path to its bundle directory."""
    queue: Queue
    """Async work queue. The API enqueues; the worker drains."""
    sla_presets: dict[SlaTier, TenantSlaConfig]
    """SLA tier → resolved config. Built from ``settings.sla_tiers_root``
    when present, falls back to the in-code presets otherwise."""


def build_app_state(settings: Settings) -> AppState:
    """Construct every long-lived adapter once at app startup."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))

    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())

    blob_store: BlobStore
    if settings.blob_backend == "local":
        blob_store = LocalBlobStore(settings.blob_local_root.resolve())
    else:
        blob_store = S3BlobStore(
            bucket=settings.blob_bucket,
            endpoint_url=settings.blob_endpoint_url,
            region=settings.blob_region,
            access_key=settings.blob_access_key,
            secret_key=settings.blob_secret_key,
        )

    vision_router = _build_vision_router(settings)

    bundle_roots = {
        target.id: (settings.targets_root / target.id).resolve() for target in target_registry.all()
    }

    sla_presets = _load_sla_presets(settings.sla_tiers_root)

    return AppState(
        settings=settings,
        encryptor=encryptor,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=blob_store,
        vision_router=vision_router,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
        queue=InMemoryQueue(),
        sla_presets=sla_presets,
    )


def _load_sla_presets(root: Path) -> dict[SlaTier, TenantSlaConfig]:
    """Resolve SLA presets from disk if available, falling back to defaults."""
    if root.exists() and root.is_dir():
        try:
            return load_presets_from_dir(root.resolve())
        except Exception:
            # Fall back to in-code defaults if preset loading fails so
            # the app still boots with reasonable defaults.
            return dict(SLA_PRESETS)
    return dict(SLA_PRESETS)


def _build_vision_router(settings: Settings) -> ProviderRouter:
    """Build the router with whichever providers are configured."""
    adapters: dict[VisionProvider, Any] = {}

    if settings.anthropic_api_key:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        adapters[VisionProvider.ANTHROPIC] = AnthropicVisionAdapter(
            client,
            primary_model="claude-haiku-4-5",
            fallback_model="claude-sonnet-4-6",
        )

    if not adapters:
        # Empty router is acceptable in development; calls to /transcripts
        # will surface a 503 NoProviderAvailableError at request time.
        # Insert a placeholder so the router constructs cleanly.
        from ocr_to_report.adapters.vision.stub_adapters import (  # noqa: PLC0415
            OpenAIVisionAdapter,
        )

        adapters[VisionProvider.OPENAI] = OpenAIVisionAdapter()

    priority = [
        VisionProvider.ANTHROPIC,
        VisionProvider.OPENAI,
        VisionProvider.GOOGLE,
        VisionProvider.TESSERACT,
    ]
    return ProviderRouter(adapters, AdaptivePolicy(priority=priority))


# ─── Per-request dependencies ────────────────────────────────
async def get_app_state(request: Request) -> AppState:
    state: AppState = request.app.state.app_state
    return state


async def get_settings(state: Annotated[AppState, Depends(get_app_state)]) -> Settings:
    return state.settings


async def get_encryptor(
    state: Annotated[AppState, Depends(get_app_state)],
) -> EnvelopeEncryptor:
    return state.encryptor


async def authenticate(
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
) -> tuple[ApiKey, Tenant, bytes]:
    """Resolve the bearer API key → (api_key row, tenant row, plaintext DEK).

    Returns a 401 with a problem-detail body on any auth failure.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise UnauthorizedError("missing bearer token in Authorization header")
    presented = auth_header[7:].strip()

    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        keys = ApiKeyRepo(session)
        api_key = await keys.authenticate(presented)
        if api_key is None:
            raise UnauthorizedError("invalid or revoked API key")
        tenants = TenantRepo(session, state.encryptor)
        tenant = await tenants.get(api_key.tenant_id)
        if tenant is None or tenant.archived_at is not None:
            raise UnauthorizedError("tenant archived or unavailable")
        dek = await tenants.unwrap_dek(tenant)
        await session.commit()

    return api_key, tenant, dek


# Convenience wrappers for individual fields ─────────────────
async def get_current_api_key(
    auth: Annotated[tuple[ApiKey, Tenant, bytes], Depends(authenticate)],
) -> ApiKey:
    return auth[0]


async def get_current_tenant(
    auth: Annotated[tuple[ApiKey, Tenant, bytes], Depends(authenticate)],
) -> Tenant:
    return auth[1]


async def get_current_dek(
    auth: Annotated[tuple[ApiKey, Tenant, bytes], Depends(authenticate)],
) -> bytes:
    return auth[2]


async def tenant_db_session(
    state: Annotated[AppState, Depends(get_app_state)],
    tenant: Annotated[Tenant, Depends(get_current_tenant)],
) -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker(state.settings.database_url)
    async with tenant_scoped_session(sm, tenant.id) as session:
        yield session


@dataclass(slots=True)
class RequestRepos:
    """Per-request bundle of repository handles.

    Built on demand from a tenant-scoped session. Every repo here knows
    its tenant via the session's RLS variable + the in-Python filter.
    """

    session: AsyncSession
    tenant: Tenant
    dek: bytes
    encryptor: EnvelopeEncryptor

    @property
    def jobs(self) -> JobRepo:
        return JobRepo(self.session)

    @property
    def transcripts(self) -> TranscriptRepo:
        return TranscriptRepo(self.session, self.encryptor)

    @property
    def audit(self) -> AuditRepo:
        return AuditRepo(self.session)

    @property
    def usage(self) -> UsageRepo:
        return UsageRepo(self.session)

    @property
    def idempotency(self) -> IdempotencyRepo:
        return IdempotencyRepo(self.session)

    @property
    def webhooks(self) -> WebhookRepo:
        return WebhookRepo(self.session, self.encryptor)

    @property
    def batch_submissions(self) -> BatchSubmissionRepo:
        return BatchSubmissionRepo(self.session)


async def get_repos(
    state: Annotated[AppState, Depends(get_app_state)],
    auth: Annotated[tuple[ApiKey, Tenant, bytes], Depends(authenticate)],
) -> AsyncIterator[RequestRepos]:
    """Yield a fully-wired :class:`RequestRepos` bound to the current tenant."""
    _api_key, tenant, dek = auth
    sm = get_sessionmaker(state.settings.database_url)
    async with tenant_scoped_session(sm, tenant.id) as session:
        yield RequestRepos(
            session=session,
            tenant=tenant,
            dek=dek,
            encryptor=state.encryptor,
        )


def resolve_sla_for_tenant(
    state: AppState,
    tenant: Tenant,
) -> TenantSlaConfig:
    """Return the SLA config to apply to this tenant's requests.

    MVP behavior: read ``tenant.sla_tier`` and look up the matching
    preset. Per-field overrides (Phase 8b extension) layer on top via
    the standard overrides resolver — not yet wired here.
    """
    try:
        tier = SlaTier(tenant.sla_tier)
    except ValueError:
        # Unknown stored value — fail safe to standard.
        tier = SlaTier.STANDARD
    return state.sla_presets.get(tier, state.sla_presets[SlaTier.STANDARD])


# ─── Lifespan ────────────────────────────────────────────────
async def shutdown_lifespan(_: FastAPI) -> None:
    """Dispose engines on app shutdown."""
    await dispose_engines()


# Suppress unused-import warning — used as type aliases above.
_ = (HTTPException, status, uuid, AsyncIterator, compile_schema, XlsxRenderer)


__all__ = [
    "AppState",
    "RequestRepos",
    "authenticate",
    "build_app_state",
    "get_app_state",
    "get_current_api_key",
    "get_current_dek",
    "get_current_tenant",
    "get_encryptor",
    "get_repos",
    "get_settings",
    "resolve_sla_for_tenant",
    "shutdown_lifespan",
    "tenant_db_session",
]

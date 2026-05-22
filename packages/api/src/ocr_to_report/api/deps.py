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
    TenantCredential,
    TenantOverrideRepo,
    TenantProviderCredentialRepo,
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
from ocr_to_report.core.errors.domain import ForbiddenError, UnauthorizedError
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import (
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    load_presets_from_dir,
)
from ocr_to_report.core.sla.resolver import resolve_with_overrides
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

    Honors the optional ``X-Acting-Tenant-Id`` header: when the calling
    key has the ``admin:*`` scope and the header points at an existing
    tenant, the returned tenant + DEK are swapped to that tenant. Every
    tenant-scoped endpoint (jobs, transcripts, webhooks, dsr, usage)
    then operates on the impersonated tenant transparently.

    Each impersonated request appends a ``tenant.impersonated_access``
    audit-log entry on the *target* tenant so an auditor can see when
    an admin viewed the data and which admin key did it.

    Non-admin keys that try to impersonate get a 403; admin keys whose
    header points at a missing/archived tenant get a 404. The 401 path
    is reserved for bad/missing bearer tokens.
    """
    auth_header = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth_header or not auth_header.lower().startswith("bearer "):
        raise UnauthorizedError("missing bearer token in Authorization header")
    presented = auth_header[7:].strip()

    acting_header = request.headers.get("x-acting-tenant-id")

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

        # Admin impersonation: swap tenant context if the header is set.
        if acting_header and acting_header != str(tenant.id):
            if "admin:*" not in _scopes_of(api_key):
                raise ForbiddenError(
                    "X-Acting-Tenant-Id requires the admin:* scope",
                    required_scope="admin:*",
                )
            try:
                acting_id = uuid.UUID(acting_header)
            except ValueError as e:
                raise ForbiddenError(
                    f"X-Acting-Tenant-Id is not a valid UUID: {acting_header!r}",
                ) from e
            target = await tenants.get(acting_id)
            if target is None or target.archived_at is not None:
                from ocr_to_report.core.errors.domain import (  # noqa: PLC0415
                    NotFoundError,
                )

                raise NotFoundError(
                    f"no tenant with id={acting_id}",
                    tenant_id=str(acting_id),
                )
            # Audit on the impersonated tenant so its auditors see the access.
            from ocr_to_report.adapters.db.repositories import (  # noqa: PLC0415
                AuditRepo,
            )

            await AuditRepo(session).append(
                tenant_id=target.id,
                actor_type="admin_api",
                actor_id_hash=str(api_key.id),
                action="tenant.impersonated_access",
                resource_type="tenant",
                resource_id=str(target.id),
                metadata={
                    "admin_tenant_id": str(api_key.tenant_id),
                    "method": request.method,
                    "path": request.url.path,
                },
            )
            tenant = target

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


def _scopes_of(api_key: ApiKey) -> list[str]:
    """Pull the scope list from the JSONB column's `{scopes: [...]}` shape."""
    raw = api_key.scopes if isinstance(api_key.scopes, dict) else {}
    out = raw.get("scopes")
    return [str(s) for s in out] if isinstance(out, list) else []


async def require_admin(
    auth: Annotated[tuple[ApiKey, Tenant, bytes], Depends(authenticate)],
) -> tuple[ApiKey, Tenant, bytes]:
    """Gate on the ``admin:*`` scope.

    Admin endpoints are cross-tenant by design; bootstrap mints an
    admin key with `--admin`, and only that key can list/create
    tenants, rotate other tenants' API keys, or view their audit
    logs.
    """
    api_key, _tenant, _dek = auth
    if "admin:*" not in _scopes_of(api_key):
        raise ForbiddenError(
            "admin scope required for this operation",
            required_scope="admin:*",
        )
    return auth


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
    """Return the SLA tier preset for this tenant — *without* overrides.

    Reads ``tenant.sla_tier`` and returns the matching preset. Per-tenant
    override patches are applied by :func:`get_resolved_tenant_config`,
    which is the dep request handlers should reach for. This function is
    kept for callers that explicitly want the un-patched baseline (e.g.
    diff previews in :mod:`tenant_config` endpoints — Task 5).
    """
    try:
        tier = SlaTier(tenant.sla_tier)
    except ValueError:
        # Unknown stored value — fail safe to standard.
        tier = SlaTier.STANDARD
    return state.sla_presets.get(tier, state.sla_presets[SlaTier.STANDARD])


# ─── Resolved tenant config (v0.2.0) ──────────────────────────


@dataclass(slots=True, frozen=True)
class ResolvedTenantConfig:
    """Tenant config with override patches applied.

    Computed once per request by :func:`get_resolved_tenant_config` and
    cached on ``request.state.resolved_tenant_config`` so multiple deps
    (SLA, pipeline selector, future ones) share a single DB read. Frozen
    because resolved config is intentionally immutable — patch changes
    only land via :mod:`tenant_config` PUTs which clobber the cache by
    starting a new request.

    Fields:

    * ``sla`` — :class:`TenantSlaConfig` after any ``scope="sla"`` patches.
    * ``pipeline_id`` — currently the tenant column's value verbatim;
      Task 5 will surface override patches that swap this on a per-tenant
      basis.
    * ``profile_overrides`` / ``target_overrides`` — raw patch lists keyed
      by ``target_id``. The pipeline runner consumes these when loading
      the profile / target bundles. None of these are applied here — they
      ride along so the rest of the request can apply them lazily.
    """

    sla: TenantSlaConfig
    pipeline_id: str
    profile_overrides: dict[str, list[dict[str, Any]]]
    target_overrides: dict[str, list[dict[str, Any]]]


async def get_resolved_tenant_config(
    request: Request,
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> ResolvedTenantConfig:
    """Resolve per-tenant overrides on top of the tier preset.

    Memoized on ``request.state.resolved_tenant_config`` so a single
    request that touches multiple endpoints (or a single handler that
    reaches for both SLA + pipeline + target overrides) only pays the
    one DB round-trip.

    Reads ride :class:`RequestRepos.session` rather than opening a
    second tenant-scoped session — saves a connection-pool slot per
    request and guarantees the resolved view sees the same snapshot as
    the repos (avoids the cross-session read/write skew where a PUT on
    /v1/tenant/config commits but the concurrent /v1/transcripts
    resolver sees the pre-PUT state).

    Patches arrive in the DB wire format (``{op, path, value}``) and are
    delegated to :func:`core.sla.resolver.resolve_with_overrides` for
    the SLA case — that's where strict Pydantic validation happens, so
    invalid patches surface as :class:`pydantic.ValidationError` (mapped
    to HTTP 400 by the existing exception handler).
    """
    cached = getattr(request.state, "resolved_tenant_config", None)
    if cached is not None:
        return cached  # type: ignore[no-any-return]

    base_sla = resolve_sla_for_tenant(state, repos.tenant)

    sla_patches: list[dict[str, Any]] = []
    profile_overrides: dict[str, list[dict[str, Any]]] = {}
    target_overrides: dict[str, list[dict[str, Any]]] = {}

    rows = await TenantOverrideRepo(repos.session).list_for_tenant(repos.tenant.id)
    for row in rows:
        if row.scope == "sla":
            sla_patches.extend(row.patches)
        elif row.scope == "profile" and row.target_id is not None:
            profile_overrides.setdefault(row.target_id, []).extend(row.patches)
        elif row.scope == "target" and row.target_id is not None:
            target_overrides.setdefault(row.target_id, []).extend(row.patches)
        # Other scopes (e.g. ``template``, ``pipeline``) are read by
        # the dedicated callers in Tasks 5 + 6 — don't snag them here.

    resolved_sla = resolve_with_overrides(base_sla, sla_patches) if sla_patches else base_sla

    config = ResolvedTenantConfig(
        sla=resolved_sla,
        pipeline_id=repos.tenant.pipeline_id,
        profile_overrides=profile_overrides,
        target_overrides=target_overrides,
    )
    request.state.resolved_tenant_config = config
    return config


async def get_current_sla(
    config: Annotated[ResolvedTenantConfig, Depends(get_resolved_tenant_config)],
) -> TenantSlaConfig:
    """Shorthand: just the resolved SLA, for endpoints that don't care
    about pipeline/profile/target overrides.

    Handlers can take ``Depends(get_current_sla)`` directly instead of
    going through the bigger :class:`ResolvedTenantConfig`. Same DB
    read either way thanks to the per-request cache.
    """
    return config.sla


# ─── BYOK credentials (v0.3.0) ────────────────────────────────


async def get_active_anthropic_credentials(
    request: Request,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> TenantCredential | None:
    """Look up the tenant's active Anthropic BYOK credential.

    Returns ``None`` when the tenant has no active row (the
    platform-billed default) or when the row exists but the encrypted
    key cannot be unwrapped (DEK rotation, ciphertext corruption — see
    the BYOK plan's "decryption-error fallback" risk note). Falling
    back to ``None`` rather than raising means a broken credential
    never breaks the request path; an alarming WARN log captures the
    credential id (never the ciphertext) for ops to investigate.

    Memoized on ``request.state.byok_credentials_anthropic`` so a
    request that hits multiple handlers (or a handler that asks for
    the dep twice) makes one DB round-trip.
    """
    cached = getattr(request.state, "byok_credentials_anthropic", _SENTINEL_MISS)
    if cached is not _SENTINEL_MISS:
        # ``cached`` was set by a previous invocation of this same dep
        # earlier in the request; its runtime type is ``TenantCredential
        # | None``. The sentinel object never leaks past this branch.
        from typing import cast  # noqa: PLC0415

        return cast("TenantCredential | None", cached)

    creds_repo = TenantProviderCredentialRepo(repos.session, repos.encryptor)
    try:
        creds = await creds_repo.get_active_for_tenant(
            repos.tenant.id, provider="anthropic", dek=repos.dek
        )
    except Exception:
        # Broad catch by design — any crypto / IO failure unwrapping the
        # key falls back to platform billing with a WARN log carrying
        # the tenant id (never the ciphertext or the credential id we
        # couldn't decrypt).
        import structlog  # noqa: PLC0415

        structlog.get_logger().warning(
            "byok_credential_unwrap_failed",
            tenant_id=str(repos.tenant.id),
            provider="anthropic",
        )
        creds = None

    request.state.byok_credentials_anthropic = creds
    return creds


# Sentinel so we can distinguish "not yet looked up" from "looked up
# and got None". Reusing a plain ``None`` default would force an extra
# DB call on every dep invocation for tenants without BYOK.
_SENTINEL_MISS = object()


# ─── Lifespan ────────────────────────────────────────────────
async def shutdown_lifespan(_: FastAPI) -> None:
    """Dispose engines on app shutdown."""
    await dispose_engines()


# Suppress unused-import warning — used as type aliases above.
_ = (HTTPException, status, uuid, AsyncIterator, compile_schema, XlsxRenderer)


__all__ = [
    "AppState",
    "RequestRepos",
    "ResolvedTenantConfig",
    "authenticate",
    "build_app_state",
    "get_active_anthropic_credentials",
    "get_app_state",
    "get_current_api_key",
    "get_current_dek",
    "get_current_sla",
    "get_current_tenant",
    "get_encryptor",
    "get_repos",
    "get_resolved_tenant_config",
    "get_settings",
    "require_admin",
    "resolve_sla_for_tenant",
    "shutdown_lifespan",
    "tenant_db_session",
]

"""Admin endpoints (cross-tenant). Gated on the ``admin:*`` scope.

What lives here:

* ``GET    /v1/admin/system``                         — top-of-funnel stats
* ``GET    /v1/admin/tenants``                        — list every tenant
* ``POST   /v1/admin/tenants``                        — create a tenant
* ``PATCH  /v1/admin/tenants/{id}``                   — update tenant config
* ``DELETE /v1/admin/tenants/{id}``                   — archive (soft delete)
* ``GET    /v1/admin/tenants/{id}/api-keys``          — list keys
* ``POST   /v1/admin/tenants/{id}/api-keys``          — issue a new key
* ``DELETE /v1/admin/api-keys/{id}``                  — revoke a key
* ``GET    /v1/admin/tenants/{id}/audit``             — recent audit entries

These endpoints are not tenant-scoped: an admin key can view + mutate
any tenant. Every action appends an audit-log entry on the *target*
tenant (so the affected tenant's auditors can see who did what).
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from ocr_to_report.adapters.db import ApiKey, Tenant, get_sessionmaker
from ocr_to_report.adapters.db.repositories import (
    ApiKeyRepo,
    AuditRepo,
    TenantRepo,
)
from ocr_to_report.api.deps import AppState, get_app_state, require_admin
from ocr_to_report.api.schemas import (
    ApiKeyIssueRequest,
    ApiKeyIssueResponse,
    ApiKeySummary,
    AuditEntrySummary,
    SystemOverview,
    TenantCreateRequest,
    TenantSummary,
    TenantUpdateRequest,
)
from ocr_to_report.api.version import get_version_info
from ocr_to_report.core.errors.domain import ConflictError, NotFoundError

router = APIRouter(prefix="/v1/admin", tags=["admin"])


# ─── System overview ─────────────────────────────────────────
@router.get("/system", response_model=SystemOverview)
async def system_overview(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
) -> SystemOverview:
    """Top-of-funnel stats for the admin dashboard."""
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        from sqlalchemy import select  # noqa: PLC0415

        from ocr_to_report.adapters.db.models import (  # noqa: PLC0415
            ApiKey as ApiKeyModel,
        )

        tenants_repo = TenantRepo(session, state.encryptor)
        all_tenants = await tenants_repo.list_all(include_archived=True)
        active_tenants = [t for t in all_tenants if t.archived_at is None]

        active_keys = await session.execute(
            select(ApiKeyModel).where(ApiKeyModel.revoked_at.is_(None))
        )
        keys_count = len(list(active_keys.scalars().all()))

    queue_depth = state.queue.pending_count() if hasattr(state.queue, "pending_count") else 0

    return SystemOverview(
        tenants_total=len(all_tenants),
        tenants_active=len(active_tenants),
        api_keys_active=keys_count,
        profiles_loaded=[p.id for p in state.profile_registry.all()],
        targets_loaded=[t.id for t in state.target_registry.all()],
        sla_presets=[t.value for t in state.sla_presets],
        queue_depth=int(queue_depth),
        api_version=get_version_info().api,
    )


# ─── Tenants ─────────────────────────────────────────────────
@router.get("/tenants", response_model=list[TenantSummary])
async def list_tenants(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    include_archived: bool = False,
) -> list[TenantSummary]:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = TenantRepo(session, state.encryptor)
        rows = await repo.list_all(include_archived=include_archived)
    return [_tenant_summary(row) for row in rows]


@router.post("/tenants", response_model=TenantSummary, status_code=201)
async def create_tenant(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    body: TenantCreateRequest,
) -> TenantSummary:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = TenantRepo(session, state.encryptor)
        existing = await repo.get_by_slug(body.slug)
        if existing is not None:
            raise ConflictError(
                f"a tenant with slug {body.slug!r} already exists",
                slug=body.slug,
            )
        tenant, _dek = await repo.create(
            name=body.name,
            slug=body.slug,
            sla_tier=body.sla_tier,
            region_pin=body.region_pin,
            default_target_system=body.default_target_system,
            pipeline_id=body.pipeline_id,
        )
        # Record on the new tenant's audit chain so every action against
        # it has provenance.
        await AuditRepo(session).append(
            tenant_id=tenant.id,
            actor_type="admin_api",
            actor_id_hash="",
            action="tenant.created",
            resource_type="tenant",
            resource_id=str(tenant.id),
            metadata={"sla_tier": body.sla_tier, "slug": body.slug},
        )
        await session.commit()
    return _tenant_summary(tenant)


@router.patch("/tenants/{tenant_id}", response_model=TenantSummary)
async def update_tenant(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    tenant_id: uuid.UUID,
    body: TenantUpdateRequest,
) -> TenantSummary:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = TenantRepo(session, state.encryptor)
        updated = await repo.update(
            tenant_id,
            name=body.name,
            sla_tier=body.sla_tier,
            region_pin=body.region_pin,
            default_target_system=body.default_target_system,
            pipeline_id=body.pipeline_id,
        )
        if updated is None:
            raise NotFoundError(
                f"no tenant with id={tenant_id}",
                tenant_id=str(tenant_id),
            )
        await AuditRepo(session).append(
            tenant_id=updated.id,
            actor_type="admin_api",
            actor_id_hash="",
            action="tenant.updated",
            resource_type="tenant",
            resource_id=str(updated.id),
            metadata=body.model_dump(exclude_none=True),
        )
        await session.commit()
    return _tenant_summary(updated)


@router.delete("/tenants/{tenant_id}", status_code=204)
async def archive_tenant(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    tenant_id: uuid.UUID,
) -> None:
    """Soft-delete: sets ``archived_at``. Use the GDPR DSR erasure
    endpoint to crypto-shred the DEK separately."""
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = TenantRepo(session, state.encryptor)
        before = await repo.get(tenant_id)
        if before is None:
            raise NotFoundError(
                f"no tenant with id={tenant_id}",
                tenant_id=str(tenant_id),
            )
        await repo.archive(tenant_id)
        await AuditRepo(session).append(
            tenant_id=tenant_id,
            actor_type="admin_api",
            actor_id_hash="",
            action="tenant.archived",
            resource_type="tenant",
            resource_id=str(tenant_id),
        )
        await session.commit()


# ─── API keys ────────────────────────────────────────────────
@router.get(
    "/tenants/{tenant_id}/api-keys",
    response_model=list[ApiKeySummary],
)
async def list_api_keys(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    tenant_id: uuid.UUID,
) -> list[ApiKeySummary]:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = ApiKeyRepo(session)
        rows = await repo.list_for_tenant(tenant_id)
    return [_api_key_summary(row) for row in rows]


@router.post(
    "/tenants/{tenant_id}/api-keys",
    response_model=ApiKeyIssueResponse,
    status_code=201,
)
async def issue_api_key(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    tenant_id: uuid.UUID,
    body: ApiKeyIssueRequest,
) -> ApiKeyIssueResponse:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        # Verify the tenant exists before minting.
        tenants = TenantRepo(session, state.encryptor)
        if await tenants.get(tenant_id) is None:
            raise NotFoundError(
                f"no tenant with id={tenant_id}",
                tenant_id=str(tenant_id),
            )
        repo = ApiKeyRepo(session)
        row, secret = await repo.issue(
            tenant_id=tenant_id,
            scopes=body.scopes,
            label=body.label,
            live=body.live,
        )
        await AuditRepo(session).append(
            tenant_id=tenant_id,
            actor_type="admin_api",
            actor_id_hash="",
            action="api_key.issued",
            resource_type="api_key",
            resource_id=str(row.id),
            metadata={"label": body.label or "", "scopes": body.scopes, "live": body.live},
        )
        await session.commit()
    return ApiKeyIssueResponse(api_key=_api_key_summary(row), secret=secret)


@router.delete("/api-keys/{api_key_id}", status_code=204)
async def revoke_api_key(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    api_key_id: uuid.UUID,
) -> None:
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        repo = ApiKeyRepo(session)
        before = await repo.get(api_key_id)
        if before is None:
            raise NotFoundError(
                f"no api key with id={api_key_id}",
                api_key_id=str(api_key_id),
            )
        await repo.revoke(api_key_id)
        await AuditRepo(session).append(
            tenant_id=before.tenant_id,
            actor_type="admin_api",
            actor_id_hash="",
            action="api_key.revoked",
            resource_type="api_key",
            resource_id=str(api_key_id),
        )
        await session.commit()


# ─── Audit ───────────────────────────────────────────────────
@router.get(
    "/tenants/{tenant_id}/audit",
    response_model=list[AuditEntrySummary],
)
async def tenant_audit(
    state: Annotated[AppState, Depends(get_app_state)],
    _admin: Annotated[tuple[ApiKey, Tenant, bytes], Depends(require_admin)],
    tenant_id: uuid.UUID,
    limit: int = 100,
) -> list[AuditEntrySummary]:
    """Recent-first audit-log slice for one tenant."""
    sm = get_sessionmaker(state.settings.database_url)
    async with sm() as session:
        rows = await AuditRepo(session).list_recent(tenant_id, limit=limit)
    return [
        AuditEntrySummary(
            id=row.id,
            ts=row.ts,
            actor_type=row.actor_type,
            action=row.action,
            resource_type=row.resource_type,
            resource_id=row.resource_id,
            metadata=row.metadata_json or {},
        )
        for row in rows
    ]


# ─── Helpers ─────────────────────────────────────────────────
def _tenant_summary(t: Tenant) -> TenantSummary:
    return TenantSummary(
        id=t.id,
        name=t.name,
        slug=t.slug,
        sla_tier=t.sla_tier,
        region_pin=t.region_pin,
        default_target_system=t.default_target_system,
        pipeline_id=t.pipeline_id,
        created_at=t.created_at,
        archived_at=t.archived_at,
    )


def _api_key_summary(row: ApiKey) -> ApiKeySummary:
    raw_scopes = row.scopes if isinstance(row.scopes, dict) else {}
    scope_list = raw_scopes.get("scopes")
    return ApiKeySummary(
        id=row.id,
        tenant_id=row.tenant_id,
        prefix=row.prefix,
        label=row.label,
        scopes=[str(s) for s in scope_list] if isinstance(scope_list, list) else [],
        created_at=row.created_at,
        last_used_at=row.last_used_at,
        revoked_at=row.revoked_at,
        expires_at=row.expires_at,
    )


__all__ = ["router"]

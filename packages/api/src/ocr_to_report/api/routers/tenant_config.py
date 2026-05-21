"""``/v1/tenant/config`` — per-tenant override CRUD.

Three endpoints cover the customer-facing surface:

* ``GET /v1/tenant/config`` — returns the **resolved** view (tier preset
  with SLA patches applied) plus the raw patch lists per scope, so the
  web UI can render both the in-effect config and the diff editor.

* ``PUT /v1/tenant/config`` — replaces the patch lists for the given
  scopes. SLA patches are dry-run through
  :func:`core.sla.resolver.resolve_with_overrides` first; bad patches
  return HTTP 400 BEFORE anything is persisted. Profile / target
  patches are wire-format-validated (op/path well-formed) but otherwise
  passed through verbatim — the pipeline will reject them at apply time
  if the path doesn't match the active bundle.

* ``POST /v1/tenant/config:preview`` — same body as PUT, but never
  persists. Returns the resolved view AS IF the patches were saved.
  Powers the web UI's "see the diff before saving" interaction.

Scope semantics:

* ``sla`` — one row per tenant, ``target_id=None``. The SLA tier preset
  is per-tenant, not per-target.
* ``profile`` — one row per ``(tenant, profile_id)``; the profile_id
  doubles as the override row's ``target_id`` column.
* ``target`` — one row per ``(tenant, target_id)``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ocr_to_report.adapters.db import Tenant
from ocr_to_report.adapters.db.repositories import TenantOverrideRepo
from ocr_to_report.api.deps import (
    AppState,
    RequestRepos,
    get_app_state,
    get_repos,
    resolve_sla_for_tenant,
)
from ocr_to_report.api.schemas import TenantConfigResponse, TenantConfigUpdate
from ocr_to_report.core.errors.domain import ConflictError
from ocr_to_report.core.overrides import patches_from_wire
from ocr_to_report.core.sla.resolver import resolve_with_overrides

router = APIRouter(prefix="/v1", tags=["tenant_config"])


# ─── GET: resolved view ───────────────────────────────────────────────


@router.get(
    "/tenant/config",
    response_model=TenantConfigResponse,
    responses={
        401: {"description": "Authentication required"},
    },
)
async def get_tenant_config(
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> TenantConfigResponse:
    """Return the resolved tenant config plus the raw patch lists."""
    return await _serialize_full(state, repos)


# ─── POST :preview: dry-run without persisting ───────────────────────


@router.post(
    "/tenant/config:preview",
    response_model=TenantConfigResponse,
    responses={
        400: {"description": "Patch is malformed or fails SLA schema validation"},
        401: {"description": "Authentication required"},
    },
)
async def preview_tenant_config(
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
    body: TenantConfigUpdate,
) -> TenantConfigResponse:
    """Apply ``body`` to the current config without persisting.

    Returns the same shape ``GET`` would return AFTER saving — the web UI
    uses this for live "if you save, here's what'll happen" diffs.
    """
    resolved = _resolve_with_replacements(state, repos, body)
    return resolved


# ─── PUT: persist after validation ───────────────────────────────────


@router.put(
    "/tenant/config",
    response_model=TenantConfigResponse,
    responses={
        400: {"description": "Patch is malformed or fails SLA schema validation"},
        401: {"description": "Authentication required"},
    },
)
async def replace_tenant_config(  # noqa: PLR0912 — three independent scope branches; further extraction obscures the CRUD shape
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
    body: TenantConfigUpdate,
) -> TenantConfigResponse:
    """Validate then persist the replacement patches; return the resolved view.

    Each scope is independent — sending ``{"sla_patches": [...]}`` only
    touches the SLA row, leaving any profile/target rows untouched. To
    clear a scope, pass an explicit empty list/dict.
    """
    # Validate everything first. ``_resolve_with_replacements`` re-uses
    # the same code path as ``:preview`` so we get identical 400s.
    _resolved_preview = _resolve_with_replacements(state, repos, body)

    overrides = TenantOverrideRepo(repos.session)
    tenant_id = repos.tenant.id

    # Pipeline switch — direct tenant column write, not a patch row.
    # Validated lazily: any non-empty string is accepted at write time;
    # the pipeline loader rejects unknown ids when a job actually runs.
    # (A future hardening pass can cross-check against
    # ``state.pipeline_loader.list_available()`` here.)
    #
    # ``repos.tenant`` was loaded inside the auth dep's session and is
    # detached from ``repos.session`` — mutating it directly wouldn't
    # be flushed. Re-fetch the row in the current session so the change
    # rides the upcoming commit.
    if body.pipeline_id is not None and body.pipeline_id != repos.tenant.pipeline_id:
        db_tenant = await repos.session.get(Tenant, repos.tenant.id)
        if db_tenant is None:
            # The row was loaded by the auth dep less than a request ago,
            # so its disappearance signals concurrent admin action
            # (archival, hard-delete) — fail loud rather than write the
            # in-memory copy and respond 200 with a value the DB doesn't
            # have. Without this guard the caller sees a successful PUT
            # whose next GET returns the old pipeline_id.
            raise ConflictError(
                "tenant row disappeared mid-request; cannot persist pipeline switch",
                tenant_id=str(repos.tenant.id),
            )
        db_tenant.pipeline_id = body.pipeline_id
        # Keep the in-memory copy aligned so the same-request response
        # reflects the change without an extra round-trip.
        repos.tenant.pipeline_id = body.pipeline_id

    if body.sla_patches is not None:
        if body.sla_patches:
            await overrides.upsert(
                tenant_id=tenant_id,
                scope="sla",
                target_id=None,
                patches=body.sla_patches,
            )
        else:
            # Empty list means "remove the SLA override row entirely".
            await overrides.delete(tenant_id=tenant_id, scope="sla", target_id=None)

    if body.profile_overrides is not None:
        # Replace-semantic: any existing profile rows not in the new dict
        # are deleted; new ones are upserted. Keeps the on-the-wire state
        # the canonical truth.
        existing_profile = {
            row.target_id: row
            for row in await overrides.list_for_tenant(
                tenant_id, scope="profile", include_disabled=True
            )
            if row.target_id is not None
        }
        for profile_id, patches in body.profile_overrides.items():
            if patches:
                await overrides.upsert(
                    tenant_id=tenant_id,
                    scope="profile",
                    target_id=profile_id,
                    patches=patches,
                )
            else:
                await overrides.delete(tenant_id=tenant_id, scope="profile", target_id=profile_id)
        for profile_id in existing_profile:
            if profile_id not in body.profile_overrides:
                await overrides.delete(tenant_id=tenant_id, scope="profile", target_id=profile_id)

    if body.target_overrides is not None:
        existing_target = {
            row.target_id: row
            for row in await overrides.list_for_tenant(
                tenant_id, scope="target", include_disabled=True
            )
            if row.target_id is not None
        }
        for target_id, patches in body.target_overrides.items():
            if patches:
                await overrides.upsert(
                    tenant_id=tenant_id,
                    scope="target",
                    target_id=target_id,
                    patches=patches,
                )
            else:
                await overrides.delete(tenant_id=tenant_id, scope="target", target_id=target_id)
        for target_id in existing_target:
            if target_id not in body.target_overrides:
                await overrides.delete(tenant_id=tenant_id, scope="target", target_id=target_id)

    await repos.session.commit()

    # Recompute the resolved view fresh from DB after the writes — the
    # ``request.state`` cache from the validation pass is stale now.
    return await _serialize_full(state, repos)


# ─── helpers ─────────────────────────────────────────────────────────


def _resolve_with_replacements(
    state: AppState,
    repos: RequestRepos,
    body: TenantConfigUpdate,
) -> TenantConfigResponse:
    """Apply ``body`` to the current state in-memory; return the resolved view.

    Used by both ``:preview`` (no persist) and the validation pass of
    ``PUT`` (so the same patch error surfaces the same way). SLA patches
    go through ``resolve_with_overrides`` which re-validates against the
    Pydantic SLA schema — bad values (out-of-range threshold,
    unknown enum) raise ``ValidationError`` → HTTP 400.
    """
    base_sla = resolve_sla_for_tenant(state, repos.tenant)
    sla_patches = body.sla_patches if body.sla_patches is not None else []
    resolved_sla = resolve_with_overrides(base_sla, sla_patches) if sla_patches else base_sla

    # Wire-format validation only for profile/target — the pipeline will
    # reject bad paths at apply time.
    profile_overrides = body.profile_overrides if body.profile_overrides is not None else {}
    for patches in profile_overrides.values():
        patches_from_wire(patches)
    target_overrides = body.target_overrides if body.target_overrides is not None else {}
    for patches in target_overrides.values():
        patches_from_wire(patches)

    # Preview surfaces the *pending* pipeline_id when the body sets it,
    # so the UI's "see the diff before saving" loop shows the user's
    # intended change rather than the current persisted value.
    pipeline_id = body.pipeline_id if body.pipeline_id is not None else repos.tenant.pipeline_id

    return TenantConfigResponse(
        sla=resolved_sla.model_dump(mode="json"),
        pipeline_id=pipeline_id,
        sla_patches=list(sla_patches),
        profile_overrides=dict(profile_overrides),
        target_overrides=dict(target_overrides),
    )


async def _serialize_full(
    state: AppState,
    repos: RequestRepos,
) -> TenantConfigResponse:
    """Read the live override rows and marshal both raw + resolved views.

    Used by ``GET`` and the ``PUT`` post-write response so the wire
    contract is identical — the caller always sees the in-DB truth
    immediately after a write, with the resolved SLA computed off the
    same patch lists they just persisted.

    Bypasses the ``get_resolved_tenant_config`` request-cache because
    a successful ``PUT`` invalidates that cache; reading fresh from
    ``repos.session`` (already tenant-scoped) is one round-trip.
    """
    base_sla = resolve_sla_for_tenant(state, repos.tenant)
    rows = await TenantOverrideRepo(repos.session).list_for_tenant(repos.tenant.id)

    sla_patches: list[dict[str, Any]] = []
    profile_overrides: dict[str, list[dict[str, Any]]] = {}
    target_overrides: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.scope == "sla":
            sla_patches.extend(row.patches)
        elif row.scope == "profile" and row.target_id is not None:
            profile_overrides.setdefault(row.target_id, []).extend(row.patches)
        elif row.scope == "target" and row.target_id is not None:
            target_overrides.setdefault(row.target_id, []).extend(row.patches)

    resolved_sla = resolve_with_overrides(base_sla, sla_patches) if sla_patches else base_sla
    return TenantConfigResponse(
        sla=resolved_sla.model_dump(mode="json"),
        pipeline_id=repos.tenant.pipeline_id,
        sla_patches=sla_patches,
        profile_overrides=profile_overrides,
        target_overrides=target_overrides,
    )


__all__ = ["router"]

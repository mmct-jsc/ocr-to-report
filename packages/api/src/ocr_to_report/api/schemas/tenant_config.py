"""Schemas for ``/v1/tenant/config``.

Three request/response shapes cover the CRUD surface:

* ``TenantConfigResponse`` — the resolved view: tier preset with SLA
  patches applied, plus the still-unrolled profile/target patch lists.
  Returned by ``GET`` and the ``:preview`` endpoint.
* ``TenantConfigUpdate`` — the wire format for ``PUT`` and ``:preview``;
  patch lists keyed by scope.

The SLA patches go through strict Pydantic re-validation via
``resolve_with_overrides`` — malformed patches surface as HTTP 400. The
profile / target patches are wire-format-validated only (``op`` is one
of the known operations, ``path`` is non-empty); deeper validation
happens lazily at pipeline-apply time so operators can save partial
patches mid-edit without the server second-guessing intent.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ─── Request bodies ──────────────────────────────────────────────────


class TenantConfigUpdate(BaseModel):
    """PUT /v1/tenant/config + POST /v1/tenant/config:preview body.

    Every field is optional — sending ``{"sla_patches": [...]}`` replaces
    JUST the SLA patches and leaves profile/target rows alone. To clear
    a scope, send an explicit empty list.

    ``pipeline_id`` is the one direct tenant column written by this
    endpoint — it's a single value (not a patch list), so a tenant
    switches between shipped pipelines (``default_v1``,
    ``with_manual_review_v1``, ``batch_economy_v1``) by sending the
    new value here.
    """

    model_config = ConfigDict(extra="forbid")

    pipeline_id: str | None = Field(
        default=None,
        description=(
            "Replacement pipeline id. Pass one of the shipped pipeline "
            "ids to switch this tenant's active pipeline. Omit the field "
            "to leave it unchanged."
        ),
    )
    sla_patches: list[dict[str, Any]] | None = Field(
        default=None,
        description=(
            "Replacement list of ``{op, path, value}`` patches for the SLA "
            "tier preset. Pass an empty list to clear all SLA overrides; "
            "omit the field entirely to leave them unchanged."
        ),
    )
    profile_overrides: dict[str, list[dict[str, Any]]] | None = Field(
        default=None,
        description=(
            "Replacement map of profile_id → patch list. Pass an empty "
            "dict to clear every profile override; omit to leave unchanged."
        ),
    )
    target_overrides: dict[str, list[dict[str, Any]]] | None = Field(
        default=None,
        description="Same shape as ``profile_overrides`` but keyed by target_id.",
    )


# ─── Response bodies ─────────────────────────────────────────────────


class TenantConfigResponse(BaseModel):
    """GET /v1/tenant/config + POST /v1/tenant/config:preview response.

    The SLA block is fully resolved (tier preset + any patches applied).
    Profile/target overrides are the *raw* patch lists for the UI to
    render in its diff editor — the pipeline applies them at job time
    against the live profile/target bundles.
    """

    model_config = ConfigDict(extra="forbid")

    sla: dict[str, Any] = Field(
        description=(
            "Resolved ``TenantSlaConfig`` as a JSON-serialisable dict. "
            "Includes every field the pipeline reads (confidence_threshold, "
            "sync_allowed, audit_detail, provider_policy, …)."
        ),
    )
    pipeline_id: str = Field(description="Currently selected pipeline id for this tenant.")
    sla_patches: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Raw SLA patch list as stored — the UI uses this to render "
            "the diff editor without re-deriving from the resolved view."
        ),
    )
    profile_overrides: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)
    target_overrides: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


__all__ = ["TenantConfigResponse", "TenantConfigUpdate"]

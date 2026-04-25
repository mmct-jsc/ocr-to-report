"""SLA tier presets + the :class:`TenantSlaConfig` data model.

Four tiers shipped with MVP:

* ``economy``   — batch-only, slowest, cheapest. Confidence ≥ 0.80.
* ``standard``  — default, sync allowed, Haiku primary. Confidence ≥ 0.85.
* ``premium``   — Sonnet primary, region pin honored, manual review
  enabled, confidence ≥ 0.95.
* ``enterprise``— same defaults as premium plus dedicated capacity hooks
  + audit-detail max + 90-day retention.

Each tier YAML lives in ``sla-tiers/<tier>.yaml`` and is loaded into a
:class:`TenantSlaConfig` at app startup. Tenants pick a tier; per-field
overrides may be applied via the standard overrides resolver.
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from ocr_to_report.core.errors.domain import ValidationError


class SlaTier(StrEnum):
    """Built-in tier identifiers."""

    ECONOMY = "economy"
    STANDARD = "standard"
    PREMIUM = "premium"
    ENTERPRISE = "enterprise"


DEFAULT_SLA_TIER: Final[SlaTier] = SlaTier.STANDARD


class TenantSlaConfig(BaseModel):
    """Resolved SLA configuration for one tenant.

    Constructed by combining a tier preset (immutable on disk) with any
    per-tenant overrides (stored in the DB). Every endpoint and worker
    handler consults this model — never the tier name directly — so a
    tenant who overrode ``confidence_threshold`` keeps that value
    regardless of what the tier preset says.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    tier: SlaTier = Field(description="Source preset tier; informational only.")

    # ─── Latency expectations ────────────────────────────────
    sync_allowed: bool = Field(
        description="If False, sync POST /v1/transcripts returns 503; "
        "all work must go through the batch endpoint.",
    )
    p95_target_seconds: float = Field(
        ge=0.0,
        description="Operational target the SLO tracks against (informational).",
    )

    # ─── Vision routing ──────────────────────────────────────
    provider_policy: Literal["batch_only", "haiku_first", "sonnet_first", "adaptive"]
    primary_model: str = Field(
        description="Default model for the primary attempt. Overridden by router.",
    )
    fallback_model: str | None = Field(
        default=None,
        description="Stronger model used when confidence below threshold.",
    )

    # ─── Confidence gate ─────────────────────────────────────
    confidence_threshold: float = Field(
        ge=0.0,
        le=1.0,
        description="Below this, the job is parked for manual review "
        "instead of returning to the caller.",
    )
    park_low_confidence: bool = Field(
        default=True,
        description="If False, low-confidence results are returned to "
        "the caller with a warning rather than being parked.",
    )

    # ─── Retention ───────────────────────────────────────────
    retention_days: int = Field(
        ge=1,
        le=3650,
        description="Days after job creation before retention sweeps the row.",
    )

    # ─── Audit + region ──────────────────────────────────────
    audit_detail: Literal["minimal", "standard", "detailed"] = "standard"
    region_pin: str | None = Field(
        default=None,
        description="If set, vision provider region is constrained.",
    )
    worm_audit: bool = Field(
        default=False,
        description="WORM audit log forwarding (Premium+ only). MVP "
        "scaffolds the flag; the integration ships with Phase 11.",
    )
    siem_export: bool = Field(
        default=False,
        description="SIEM (Splunk/Datadog/etc) export (Enterprise only).",
    )


# ─── Loading ─────────────────────────────────────────────────
def load_preset(tier: SlaTier, *, root: Path) -> TenantSlaConfig:
    """Load a single tier preset from ``<root>/<tier>.yaml``."""
    path = root / f"{tier.value}.yaml"
    if not path.is_file():
        raise ValidationError(
            f"sla preset not found: {path}",
            tier=tier.value,
            path=str(path),
        )
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValidationError(
            f"sla preset {path} must be a YAML mapping",
            tier=tier.value,
        )
    raw_dict: dict[str, Any] = dict(raw)
    raw_dict.setdefault("tier", tier.value)
    return TenantSlaConfig.model_validate(raw_dict, strict=False)


def load_presets_from_dir(root: Path) -> dict[SlaTier, TenantSlaConfig]:
    """Load all four tier presets from ``root``."""
    return {tier: load_preset(tier, root=root) for tier in SlaTier}


# ─── Built-in defaults (used when no YAML root is supplied) ──
SLA_PRESETS: Final[dict[SlaTier, TenantSlaConfig]] = {
    SlaTier.ECONOMY: TenantSlaConfig(
        tier=SlaTier.ECONOMY,
        sync_allowed=False,
        p95_target_seconds=24 * 60 * 60.0,
        provider_policy="batch_only",
        primary_model="claude-haiku-4-5",
        fallback_model=None,
        confidence_threshold=0.80,
        park_low_confidence=False,
        retention_days=7,
        audit_detail="minimal",
    ),
    SlaTier.STANDARD: TenantSlaConfig(
        tier=SlaTier.STANDARD,
        sync_allowed=True,
        p95_target_seconds=30.0,
        provider_policy="haiku_first",
        primary_model="claude-haiku-4-5",
        fallback_model="claude-sonnet-4-6",
        confidence_threshold=0.85,
        park_low_confidence=True,
        retention_days=30,
        audit_detail="standard",
    ),
    SlaTier.PREMIUM: TenantSlaConfig(
        tier=SlaTier.PREMIUM,
        sync_allowed=True,
        p95_target_seconds=15.0,
        provider_policy="sonnet_first",
        primary_model="claude-sonnet-4-6",
        fallback_model="claude-opus-4-7",
        confidence_threshold=0.95,
        park_low_confidence=True,
        retention_days=60,
        audit_detail="detailed",
        worm_audit=True,
    ),
    SlaTier.ENTERPRISE: TenantSlaConfig(
        tier=SlaTier.ENTERPRISE,
        sync_allowed=True,
        p95_target_seconds=10.0,
        provider_policy="sonnet_first",
        primary_model="claude-sonnet-4-6",
        fallback_model="claude-opus-4-7",
        confidence_threshold=0.95,
        park_low_confidence=True,
        retention_days=90,
        audit_detail="detailed",
        worm_audit=True,
        siem_export=True,
    ),
}


__all__ = [
    "DEFAULT_SLA_TIER",
    "SLA_PRESETS",
    "SlaTier",
    "TenantSlaConfig",
    "load_preset",
    "load_presets_from_dir",
]

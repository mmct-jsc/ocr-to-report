"""SLA tier domain model + per-tenant override resolver.

A tenant picks one of four built-in tiers — :class:`SlaTier` — that fills
a :class:`TenantSlaConfig` with sane defaults. Per-field overrides on
top of the tier preset are merged via :func:`resolve_with_overrides`,
which composes :mod:`core.overrides` with the SLA-specific Pydantic
re-validation gate.

This module is pure-Python types + the YAML preset loader + the
override resolver. The actual *enforcement* (confidence gate, provider
routing, retention windows) happens in the API/worker layers that
consume :class:`TenantSlaConfig`.
"""

from ocr_to_report.core.sla.config import (
    DEFAULT_SLA_TIER,
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    load_preset,
    load_presets_from_dir,
)
from ocr_to_report.core.sla.resolver import resolve_with_overrides

__all__ = [
    "DEFAULT_SLA_TIER",
    "SLA_PRESETS",
    "SlaTier",
    "TenantSlaConfig",
    "load_preset",
    "load_presets_from_dir",
    "resolve_with_overrides",
]

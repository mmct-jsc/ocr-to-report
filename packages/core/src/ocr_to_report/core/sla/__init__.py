"""SLA tier domain model.

A tenant picks one of four built-in tiers — :class:`SlaTier` — that fills
a :class:`TenantSlaConfig` with sane defaults. Per-field overrides on
top of the tier preset are merged via :mod:`core.overrides`.

This module is pure-Python types + the YAML preset loader. The actual
*enforcement* (confidence gate, provider routing, retention windows)
happens in the API/worker layers that consume :class:`TenantSlaConfig`.
"""

from ocr_to_report.core.sla.config import (
    DEFAULT_SLA_TIER,
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    load_preset,
    load_presets_from_dir,
)

__all__ = [
    "DEFAULT_SLA_TIER",
    "SLA_PRESETS",
    "SlaTier",
    "TenantSlaConfig",
    "load_preset",
    "load_presets_from_dir",
]

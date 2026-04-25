"""Tenant override resolver — kustomize-style deep merge over bundle dicts.

Tenants override profile/target defaults via JSON-Patch-shaped operations
applied at load time. This module is pure: take a base dict and a list of
patches, return a new dict.
"""

from ocr_to_report.core.overrides.resolver import (
    OverrideError,
    OverrideOperation,
    OverridePatch,
    apply_overrides,
)

__all__ = [
    "OverrideError",
    "OverrideOperation",
    "OverridePatch",
    "apply_overrides",
]

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
from ocr_to_report.core.overrides.wire import patch_from_wire, patches_from_wire

__all__ = [
    "OverrideError",
    "OverrideOperation",
    "OverridePatch",
    "apply_overrides",
    "patch_from_wire",
    "patches_from_wire",
]

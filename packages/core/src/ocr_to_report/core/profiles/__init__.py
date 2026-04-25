"""Source profile loading and registry.

Pure logic — reads YAML from disk via :func:`load_profile_bundle` and
caches results in :class:`ProfileRegistry`. The Pydantic *types* live in
:mod:`ocr_to_report.core.profile` (singular); this module is the runtime
machinery (plural).
"""

from ocr_to_report.core.profiles.loader import (
    ProfileLoadError,
    load_profile_bundle,
)
from ocr_to_report.core.profiles.registry import ProfileRegistry

__all__ = ["ProfileLoadError", "ProfileRegistry", "load_profile_bundle"]

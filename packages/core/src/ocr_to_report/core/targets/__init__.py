"""Target system loading and registry.

The Pydantic *types* live in :mod:`ocr_to_report.core.target` (singular);
this module is the runtime machinery (plural).
"""

from ocr_to_report.core.targets.loader import (
    TargetLoadError,
    load_target_bundle,
)
from ocr_to_report.core.targets.registry import TargetRegistry

__all__ = ["TargetLoadError", "TargetRegistry", "load_target_bundle"]

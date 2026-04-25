"""Mapping engine: raw extraction → canonical IR → target render data.

The mapping engine is split into two halves:

* :mod:`extraction` — converts a profile-shaped raw extraction (the dict
  produced by a vision adapter in Phase 3) into a strongly-typed
  :class:`CanonicalTranscript`.
* :mod:`render_data` — converts a :class:`CanonicalTranscript` plus a
  :class:`TargetBundle` into a flat dict of ``cell_reference → value``
  ready for the openpyxl renderer (Phase 4).

Both halves are pure: no I/O, no globals.
"""

from ocr_to_report.core.mapping.extraction import (
    CANONICAL_EXTRACTION_FIELDS,
    extract_to_canonical,
)
from ocr_to_report.core.mapping.render_data import (
    RenderCellValue,
    RenderData,
    canonical_to_render_data,
)

__all__ = [
    "CANONICAL_EXTRACTION_FIELDS",
    "RenderCellValue",
    "RenderData",
    "canonical_to_render_data",
    "extract_to_canonical",
]

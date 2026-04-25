"""PII classification and redaction primitives.

Public API:

* :class:`PIIClass` — six-level classification taxonomy.
* :func:`redacted_dump` — produce a dict view of a Pydantic model with
  sensitive fields replaced by markers.
* :func:`redact_log_event` — structlog processor for auto-redaction.
* :func:`get_field_pii_class`, :func:`model_pii_map` — read annotations
  reflectively (used by adapters and rendering code).
"""

from ocr_to_report.core.pii.annotations import (
    field_pii_class,
    get_field_pii_class,
    model_pii_map,
)
from ocr_to_report.core.pii.classes import PIIClass
from ocr_to_report.core.pii.redaction import redact_log_event, redacted_dump

__all__ = [
    "PIIClass",
    "field_pii_class",
    "get_field_pii_class",
    "model_pii_map",
    "redact_log_event",
    "redacted_dump",
]

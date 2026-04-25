"""PII-aware redaction for logging and audit metadata.

Two surfaces:

* :func:`redacted_dump` — replaces PII fields in a Pydantic model with their
  redaction markers. Use for log output, webhook payloads (default), and
  audit metadata.
* :func:`redact_log_event` — a structlog processor that recursively visits
  log event values and applies :func:`redacted_dump` to any Pydantic models
  it finds.

Hashing of redacted values (for audit chain) lives in `core/audit/` (Phase 5);
this module concerns itself only with log/webhook output.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from ocr_to_report.core.pii.annotations import model_pii_map
from ocr_to_report.core.pii.classes import PIIClass

if TYPE_CHECKING:
    from collections.abc import MutableMapping


def redacted_dump(
    model: BaseModel,
    *,
    keep: frozenset[PIIClass] = frozenset(),
) -> dict[str, Any]:
    """Return a dict view of `model` with sensitive fields replaced by markers.

    Args:
        model: The Pydantic model instance to dump.
        keep: PII classes that should NOT be redacted. Use this for
            controlled contexts (e.g., a tenant-authorized webhook with
            `redaction_level=none` for `PII_DIRECT` only). Default: redact
            every sensitive class.

    Nested Pydantic models are redacted recursively. Lists, tuples, sets,
    and dicts are walked.
    """
    pii_map = model_pii_map(type(model))
    result: dict[str, Any] = {}
    for field_name in type(model).model_fields:
        value = getattr(model, field_name)
        cls = pii_map.get(field_name)
        if cls is not None and cls.is_sensitive() and cls not in keep:
            result[field_name] = cls.redaction_marker()
        else:
            result[field_name] = _walk(value, keep)
    return result


def _walk(value: Any, keep: frozenset[PIIClass]) -> Any:  # noqa: PLR0911 — clear dispatch
    """Recurse into containers; redact any nested Pydantic models."""
    if isinstance(value, BaseModel):
        return redacted_dump(value, keep=keep)
    if isinstance(value, dict):
        return {k: _walk(v, keep) for k, v in value.items()}
    if isinstance(value, list):
        return [_walk(v, keep) for v in value]
    if isinstance(value, tuple):
        return tuple(_walk(v, keep) for v in value)
    if isinstance(value, set | frozenset):
        return type(value)(_walk(v, keep) for v in value)
    # Convert non-trivially-JSON-serializable types to a serializable form
    # so that callers can json.dumps the result without surprises.
    if hasattr(value, "isoformat"):  # date / datetime
        return value.isoformat()
    return value


def redact_log_event(
    _logger: object,
    _name: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor — applies :func:`redacted_dump` recursively.

    Wire into structlog's processor chain. Any Pydantic model attached to
    a log event is auto-redacted; plain dicts/lists are walked but only
    their nested Pydantic models are redacted (we don't redact arbitrary
    keys unless they belong to a known model — that's by design to avoid
    eating user-supplied log fields named "name" etc.).
    """
    for key, value in list(event_dict.items()):
        event_dict[key] = _walk(value, frozenset())
    return event_dict


__all__ = ["redact_log_event", "redacted_dump"]

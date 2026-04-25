"""Compile a :class:`ProfileExtractionSchema` into a JSON Schema.

The vision adapter takes a JSON Schema in :class:`VisionRequest`. Profiles
declare their extraction shape via :class:`ExtractionField` records; this
module is the bridge.
"""

from __future__ import annotations

from typing import Any

from ocr_to_report.core.profile.extraction_schema import (
    ExtractionField,
    ExtractionFieldKind,
    ProfileExtractionSchema,
)


def compile_schema(schema: ProfileExtractionSchema) -> dict[str, Any]:
    """Turn a profile extraction schema into a JSON Schema object.

    The output is a single top-level object schema with one property per
    field. The vision adapter wraps this with its own ``_meta`` envelope
    (see :func:`anthropic_adapter._wrap_schema`) before sending to the
    model.
    """
    properties: dict[str, Any] = {}
    required: list[str] = []
    for f in schema.fields:
        properties[f.name] = _compile_field(f)
        if f.required:
            required.append(f.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _compile_field(f: ExtractionField) -> dict[str, Any]:  # noqa: PLR0912 — field-kind dispatch
    base: dict[str, Any] = {"description": f.description}

    kind = f.kind
    if kind is ExtractionFieldKind.STRING:
        base["type"] = "string"
        if f.validation_pattern:
            base["pattern"] = f.validation_pattern
    elif kind is ExtractionFieldKind.DATE:
        base["type"] = "string"
        base["format"] = "date"
        if f.validation_pattern:
            base["pattern"] = f.validation_pattern
    elif kind is ExtractionFieldKind.INTEGER:
        base["type"] = "integer"
    elif kind is ExtractionFieldKind.BOOLEAN:
        base["type"] = "boolean"
    elif kind is ExtractionFieldKind.LIST_STRING:
        base["type"] = "array"
        base["items"] = {"type": "string"}
    elif kind is ExtractionFieldKind.SUBJECT_TABLE:
        base["type"] = "array"
        base["items"] = {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "raw_subject_name": {
                    "type": "string",
                    "description": "Subject name as printed on the transcript.",
                },
                "raw_grade_value": {
                    "type": ["string", "null"],
                    "description": "Grade word/number as printed; null if no grade given.",
                },
                "notes": {
                    "type": ["string", "null"],
                    "description": "Free-text note (e.g., '-' for opt-out).",
                },
            },
            "required": ["raw_subject_name"],
        }
    elif kind is ExtractionFieldKind.ADVANCED_SUBJECTS:
        base["type"] = "array"
        base["items"] = {"type": "string"}
    else:  # pragma: no cover — exhaustive enum covered above
        raise ValueError(f"unhandled extraction field kind: {kind}")

    if not f.required:
        # Allow null for optional fields so the model can explicitly say
        # "absent" instead of fabricating a string.
        existing_type = base.get("type")
        if isinstance(existing_type, str):
            base["type"] = [existing_type, "null"]

    if f.examples:
        base["examples"] = list(f.examples)

    return base


__all__ = ["compile_schema"]

"""Pydantic-aware machinery for reading PII annotations off models.

Usage pattern in domain models:

    from typing import Annotated
    from ocr_to_report.core.pii import PIIClass

    class StudentInfo(BaseModel):
        full_name: Annotated[str, PIIClass.PII_DIRECT]
        birth_date: Annotated[date | None, PIIClass.PII_DIRECT] = None
        school_name: Annotated[str, PIIClass.PII_QUASI]

The functions in this module read these annotations to drive redaction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ocr_to_report.core.pii.classes import PIIClass

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pydantic import BaseModel


def get_field_pii_class(model: type[BaseModel], field_name: str) -> PIIClass | None:
    """Return the highest-sensitivity :class:`PIIClass` annotating a field, if any.

    A single field may carry multiple metadata items; we take the most
    sensitive class found. Returns None if the field is not annotated.

    Raises :class:`KeyError` if `field_name` is not a field of `model`.
    """
    field_info = model.model_fields[field_name]
    classes: list[PIIClass] = [m for m in field_info.metadata if isinstance(m, PIIClass)]
    if not classes:
        return None
    # Order by enum definition order ascending; "more sensitive" = later.
    order = list(PIIClass)
    return max(classes, key=order.index)


def model_pii_map(model: type[BaseModel]) -> Mapping[str, PIIClass]:
    """Map every PII-annotated field of `model` to its effective class.

    Fields without a PIIClass annotation are omitted.
    """
    result: dict[str, PIIClass] = {}
    for name in model.model_fields:
        cls = get_field_pii_class(model, name)
        if cls is not None:
            result[name] = cls
    return result


def field_pii_class(field_value: Any) -> PIIClass | None:
    """Read a PIIClass directly off an `Annotated[...]` value reflectively.

    Useful for ad-hoc inspection in tests / debugging. Returns None if no
    PIIClass is found in the annotation metadata.
    """
    metadata = getattr(field_value, "__metadata__", ())
    classes = [m for m in metadata if isinstance(m, PIIClass)]
    if not classes:
        return None
    order = list(PIIClass)
    return max(classes, key=order.index)


__all__ = ["field_pii_class", "get_field_pii_class", "model_pii_map"]

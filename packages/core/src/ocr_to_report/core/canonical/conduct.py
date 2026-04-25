"""Canonical conduct record."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from ocr_to_report.core.enums.canonical import CanonicalConductLevel
from ocr_to_report.core.pii.classes import PIIClass
from ocr_to_report.core.types import Confidence


class CanonicalConduct(BaseModel):
    """Behavioral conduct (zachowanie in PL) on the canonical 6-level scale."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    level: Annotated[CanonicalConductLevel | None, PIIClass.EDUCATIONAL] = Field(
        default=None,
        description="Canonical conduct level (None if not present on the source).",
    )
    raw_source_value: str | None = Field(
        default=None,
        max_length=64,
        description="Original conduct word (e.g., 'wzorowe', 'bardzo dobre').",
    )
    confidence: Confidence = Field(
        default=1.0,
        description="Extraction confidence in the conduct value.",
    )


__all__ = ["CanonicalConduct"]

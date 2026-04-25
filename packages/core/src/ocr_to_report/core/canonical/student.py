"""Canonical student bio + academic-progress record."""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ocr_to_report.core.pii.classes import PIIClass
from ocr_to_report.core.types import Confidence


class CanonicalStudent(BaseModel):
    """Student record, language-neutral.

    Year indices use the source education system's 1-based numbering
    (e.g., for Polish liceum: 1=pierwszej, 2=drugiej, 3=trzeciej, 4=czwartej).
    Mapping to a target system's year scale is performed by the target's
    bundle (e.g., us-hs.v1 maps source_year=1 → grade 9), not here.

    Invariants:
    1. ``school_year`` matches the canonical "YYYY/YYYY" form, with the
       second year following the first by exactly 1.
    2. ``target_year_index`` equals ``source_year_index + 1`` if
       ``promoted`` else ``source_year_index``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    full_name: Annotated[str, PIIClass.PII_DIRECT] = Field(
        min_length=1,
        max_length=200,
        description="Student's full name as printed on the transcript.",
    )
    birth_date: Annotated[date | None, PIIClass.PII_DIRECT] = Field(
        default=None,
        description="Date of birth, or None if not extracted.",
    )

    school_year: str = Field(
        min_length=9,
        max_length=9,
        description="Academic year in 'YYYY/YYYY' form (e.g., '2023/2024').",
    )

    source_year_index: int = Field(
        ge=1,
        le=12,
        description="1-based year index in the *source* education system "
        "(1 = first year of the source system).",
    )
    target_year_index: int = Field(
        ge=1,
        le=13,
        description="1-based year index for the year the student is being "
        "evaluated *for* (= source_year_index + 1 if promoted, else "
        "source_year_index).",
    )
    promoted: bool = Field(
        default=True,
        description="True if the transcript indicates promotion to the next year.",
    )
    promoted_with_distinction: bool = Field(
        default=False,
        description="True for 'promocja z wyróżnieniem' or equivalent.",
    )

    school_name: Annotated[str, PIIClass.PII_QUASI] = Field(
        min_length=1,
        max_length=200,
        description="Name of the issuing school.",
    )
    city: Annotated[str | None, PIIClass.PII_QUASI] = Field(
        default=None,
        max_length=120,
        description="City / locality where the school is located.",
    )
    region: Annotated[str | None, PIIClass.PII_QUASI] = Field(
        default=None,
        max_length=120,
        description="Sub-national region (PL: voivodeship; ES: comunidad; etc.).",
    )

    confidence: Confidence = Field(
        default=1.0,
        description="Extraction confidence for the student bio block as a whole.",
    )

    @field_validator("school_year")
    @classmethod
    def _school_year_format(cls, v: str) -> str:
        m = re.fullmatch(r"(\d{4})/(\d{4})", v)
        if m is None:
            raise ValueError(f"school_year must be 'YYYY/YYYY', got {v!r}")
        y1, y2 = int(m.group(1)), int(m.group(2))
        if y2 != y1 + 1:
            raise ValueError(f"school_year second year must follow first by 1, got {v!r}")
        return v

    @model_validator(mode="after")
    def _target_year_consistent(self) -> Self:
        expected = self.source_year_index + (1 if self.promoted else 0)
        if self.target_year_index != expected:
            raise ValueError(
                f"target_year_index {self.target_year_index} inconsistent with "
                f"source_year_index {self.source_year_index} + promoted={self.promoted}; "
                f"expected {expected}"
            )
        return self


__all__ = ["CanonicalStudent"]

"""Canonical subject record — one row in a transcript's grade table."""

from __future__ import annotations

from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.canonical.grade import CanonicalGrade
from ocr_to_report.core.enums.canonical import CanonicalSubjectId
from ocr_to_report.core.pii.classes import PIIClass
from ocr_to_report.core.types import Confidence

# Polish-curriculum specific bonus hours for "extended" subjects. The value
# is profile-configurable in the source profile bundle; this constant is the
# Polish default and is only used by the Polish profile's mapping rules.
# Other profiles set their own offset via the profile YAML.
DEFAULT_ADVANCED_HOUR_BONUS = 27


class CanonicalSubject(BaseModel):
    """A subject row in canonical form.

    Invariants:
    1. ``total_hours`` equals ``base_hours + advanced_hour_bonus`` when
       ``is_advanced``; equals ``base_hours`` otherwise.
    2. ``confidence`` ∈ [0, 1].
    3. If ``canonical_id`` is None, the subject is unrecognized — ``notes``
       should usually carry context for downstream reviewers.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    canonical_id: CanonicalSubjectId | None = Field(
        default=None,
        description="Canonical subject id, or None if the source name was "
        "not in the profile vocabulary.",
    )
    raw_source_name: Annotated[str, PIIClass.EDUCATIONAL] = Field(
        min_length=1,
        max_length=200,
        description="Original subject name as it appeared on the transcript.",
    )
    grade: Annotated[CanonicalGrade | None, PIIClass.EDUCATIONAL] = Field(
        default=None,
        description="The grade for this subject (None if not graded; e.g., a P/E exemption row).",
    )
    base_hours: int | None = Field(
        default=None,
        ge=0,
        le=400,
        description="Annual instruction hours (base, before advanced bonus).",
    )
    is_advanced: bool = Field(
        default=False,
        description="True if listed under 'extended subjects' (PL: rozszerzonym).",
    )
    advanced_hour_bonus: int = Field(
        default=DEFAULT_ADVANCED_HOUR_BONUS,
        ge=0,
        le=400,
        description="Extra hours added when is_advanced. Profile-configurable; "
        "Polish default is +27h.",
    )
    confidence: Confidence = Field(
        default=1.0,
        description="Extraction confidence in this entire subject row.",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
        description="Free-text notes (e.g., '-' for opt-out / 'no grade given').",
    )

    @property
    def total_hours(self) -> int | None:
        """Effective annual hours including advanced bonus, or None if no
        base_hours were captured."""
        if self.base_hours is None:
            return None
        return self.base_hours + (self.advanced_hour_bonus if self.is_advanced else 0)

    @model_validator(mode="after")
    def _confidence_consistent_with_grade(self) -> Self:
        # If a grade is present, the row's confidence cannot exceed the
        # grade's own confidence — confidence flows monotonically upward.
        if self.grade is not None and self.confidence > self.grade.confidence + 1e-9:
            raise ValueError(
                f"row confidence {self.confidence} exceeds grade confidence "
                f"{self.grade.confidence}; should be ≤"
            )
        return self


__all__ = ["DEFAULT_ADVANCED_HOUR_BONUS", "CanonicalSubject"]

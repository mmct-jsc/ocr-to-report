"""Canonical (language-neutral) grade representation.

A :class:`CanonicalGrade` is the IR every source-side scale maps *into* and
every target-side scale maps *out of*. It carries both a normalized
quality score and a categorical level so target systems can choose the
closer match.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.enums.canonical import CanonicalGradeLevel
from ocr_to_report.core.types import Confidence

# Cutoff values (lower bound, inclusive) for each categorical level.
# Each level occupies a contiguous slice of [0, 1]. EXCELLENT spans the top
# slice [5/6, 1.0]. Cutoffs deliberately use sixths to round-trip the Polish
# 6-point scale without information loss.
_LEVEL_LOWER_BOUNDS: dict[CanonicalGradeLevel, float] = {
    CanonicalGradeLevel.FAIL: 0.0,
    CanonicalGradeLevel.PASS: 1 / 6,
    CanonicalGradeLevel.SATISFACTORY: 2 / 6,
    CanonicalGradeLevel.GOOD: 3 / 6,
    CanonicalGradeLevel.VERY_GOOD: 4 / 6,
    CanonicalGradeLevel.EXCELLENT: 5 / 6,
}

# Tiny epsilon to forgive float equality near boundaries.
_EPS = 1e-9


def categorical_for(level_normalized: float) -> CanonicalGradeLevel:
    """Return the categorical level that contains the given normalized score.

    Out-of-range inputs raise ``ValueError`` (use Pydantic validation upstream
    to ensure 0.0..1.0 before calling).
    """
    if level_normalized < 0.0 - _EPS or level_normalized > 1.0 + _EPS:
        raise ValueError(f"level_normalized must be in [0,1], got {level_normalized}")
    # Iterate from highest to lowest band; first whose lower bound is met wins.
    for lvl in reversed(list(CanonicalGradeLevel)):
        if level_normalized + _EPS >= _LEVEL_LOWER_BOUNDS[lvl]:
            return lvl
    return CanonicalGradeLevel.FAIL


class CanonicalGrade(BaseModel):
    """A grade in the language-neutral canonical form.

    Invariants (enforced by the model validator):
    1. ``level_normalized`` ∈ [0, 1].
    2. ``level_categorical`` matches the band that contains
       ``level_normalized`` (within ``_EPS``).
    3. ``raw_source_scale_id`` and ``raw_source_value`` are both present
       (so we can round-trip back to the source system).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    level_normalized: float = Field(
        ge=0.0,
        le=1.0,
        description="Normalized quality score on the canonical 0..1 scale.",
    )
    level_categorical: CanonicalGradeLevel = Field(
        description="Categorical 6-level bucket containing level_normalized.",
    )
    raw_source_value: str = Field(
        min_length=1,
        max_length=64,
        description="Original source-side value (e.g., 'bardzo dobry', '5', 'A-').",
    )
    raw_source_scale_id: str = Field(
        min_length=1,
        max_length=64,
        description="ID of the source-side scale this grade came from "
        "(e.g., 'pl.6point.v1', 'us.letter.v1').",
    )
    confidence: Confidence = Field(
        default=1.0,
        description="Extraction confidence in this specific grade (0..1).",
    )

    @model_validator(mode="after")
    def _categorical_matches_normalized(self) -> Self:
        expected = categorical_for(self.level_normalized)
        if expected != self.level_categorical:
            raise ValueError(
                f"level_categorical {self.level_categorical} inconsistent with "
                f"level_normalized {self.level_normalized}; expected {expected}"
            )
        return self

    @classmethod
    def from_normalized(
        cls,
        level_normalized: float,
        *,
        raw_source_value: str,
        raw_source_scale_id: str,
        confidence: float = 1.0,
    ) -> CanonicalGrade:
        """Construct a CanonicalGrade by deriving the categorical level."""
        return cls(
            level_normalized=level_normalized,
            level_categorical=categorical_for(level_normalized),
            raw_source_value=raw_source_value,
            raw_source_scale_id=raw_source_scale_id,
            confidence=confidence,
        )


__all__ = ["CanonicalGrade", "categorical_for"]

"""Source-side grade scale schema.

A grade scale is an ordered set of named levels each with a normalized
quality score in [0, 1]. The Polish 6-point scale, the Vietnamese 10-point
scale, the German 1-6 scale, and the IB 1-7 scale are all instances.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.types import Confidence


class GradeScaleLevel(BaseModel):
    """One level on a grade scale."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    raw_value: str = Field(
        min_length=1,
        max_length=64,
        description="Canonical raw value as it appears on the source document.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Alternative spellings or numeric forms recognized as "
        "this level (e.g., '5' for 'bardzo dobry').",
    )
    normalized: float = Field(
        ge=0.0,
        le=1.0,
        description="Position on the canonical 0..1 scale.",
    )
    label: str = Field(
        min_length=1,
        max_length=64,
        description="Display label (often the same as raw_value).",
    )
    is_passing: bool = Field(
        description="True if this level is a passing grade.",
    )
    confidence: Confidence = Field(
        default=1.0,
        description="Confidence that an instance recognized at this level "
        "is actually this level. Use values <1 for ambiguous levels (e.g., "
        "near scale boundaries) so downstream confidence flows up correctly.",
    )


class ProfileGradeScale(BaseModel):
    """A complete grade scale for a source education system.

    Invariants:
    1. Levels are sorted ascending by ``normalized``.
    2. Aliases (across all levels and ``raw_value``s) are unique.
    3. At least one passing and one failing level present.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(
        min_length=1,
        max_length=64,
        description="Stable id (e.g., 'pl.6point.v1', 'vi.10point.v1').",
    )
    description: str | None = Field(
        default=None,
        max_length=500,
    )
    levels: list[GradeScaleLevel] = Field(
        min_length=2,
        max_length=20,
        description="Ordered ascending by normalized score.",
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        # Ascending order
        normalized = [lvl.normalized for lvl in self.levels]
        if normalized != sorted(normalized):
            raise ValueError("grade scale levels must be sorted ascending by normalized")

        # Uniqueness of every recognized token
        seen: set[str] = set()
        for lvl in self.levels:
            for token in (lvl.raw_value, *lvl.aliases):
                key = token.casefold().strip()
                if key in seen:
                    raise ValueError(f"duplicate alias / raw_value across scale: {token!r}")
                seen.add(key)

        if not any(lvl.is_passing for lvl in self.levels):
            raise ValueError("grade scale must include at least one passing level")
        if not any(not lvl.is_passing for lvl in self.levels):
            raise ValueError("grade scale must include at least one failing level")

        return self

    def lookup(self, raw_or_alias: str) -> GradeScaleLevel | None:
        """Find the level whose raw_value or alias matches (case-fold, trimmed).

        Returns None if no match.
        """
        key = raw_or_alias.casefold().strip()
        for lvl in self.levels:
            if lvl.raw_value.casefold().strip() == key:
                return lvl
            if any(a.casefold().strip() == key for a in lvl.aliases):
                return lvl
        return None


__all__ = ["GradeScaleLevel", "ProfileGradeScale"]

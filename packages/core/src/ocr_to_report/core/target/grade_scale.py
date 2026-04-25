"""Target-side grade scale + canonical-to-target mapping."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.enums.canonical import CanonicalGradeLevel


class TargetGradeScaleLevel(BaseModel):
    """One level on the target grade scale.

    Each level declares which canonical levels map to it. Multiple
    canonical levels may map to a single target level (e.g., Polish PASS
    in US-HS maps to ``D-E`` covering both US 'D' and 'E').
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    display_value: str = Field(
        min_length=1,
        max_length=16,
        description="What appears in the rendered output (e.g., 'A+', 'B', '4.0').",
    )
    canonical_levels: list[CanonicalGradeLevel] = Field(
        min_length=1,
        max_length=6,
        description="Canonical levels that map to this target level.",
    )
    label: str = Field(
        min_length=1,
        max_length=64,
        description="Long-form label (e.g., 'Excellent', 'Very Good').",
    )


class TargetGradeScale(BaseModel):
    """Full target-side grade scale.

    Invariants:
    1. Every canonical level appears in exactly one target level (i.e.,
       the union of canonical_levels across all target levels is the full
       :class:`CanonicalGradeLevel` enum and they don't overlap).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    levels: list[TargetGradeScaleLevel] = Field(min_length=2, max_length=20)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        seen: dict[CanonicalGradeLevel, str] = {}
        for tlvl in self.levels:
            for clvl in tlvl.canonical_levels:
                if clvl in seen:
                    raise ValueError(
                        f"canonical level {clvl} mapped to multiple target levels: "
                        f"{seen[clvl]!r} and {tlvl.display_value!r}"
                    )
                seen[clvl] = tlvl.display_value
        missing = set(CanonicalGradeLevel) - set(seen)
        if missing:
            raise ValueError(
                f"target grade scale leaves canonical levels unmapped: {sorted(missing)}"
            )
        return self

    def for_canonical(self, level: CanonicalGradeLevel) -> TargetGradeScaleLevel:
        """Return the target level that contains the given canonical level."""
        for tlvl in self.levels:
            if level in tlvl.canonical_levels:
                return tlvl
        raise ValueError(f"canonical level {level} not mapped (validator should have caught this)")


__all__ = ["TargetGradeScale", "TargetGradeScaleLevel"]

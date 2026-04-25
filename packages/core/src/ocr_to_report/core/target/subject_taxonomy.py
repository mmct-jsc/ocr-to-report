"""Target-side subject taxonomy.

Maps :class:`CanonicalSubjectId` to the target system's display name and
expected base hours per year. Per-year hour overrides allow systems where
hours per subject vary by grade (e.g., Polish curriculum: Math = 108h in
year 1 but 81h in year 2).
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.enums.canonical import CanonicalSubjectId


class TargetSubjectEntry(BaseModel):
    """How a canonical subject is presented in this target system."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    canonical_id: CanonicalSubjectId
    display_name: str = Field(
        min_length=1,
        max_length=200,
        description="Display name in this target's output language "
        "(e.g., 'Mathematics' for us-hs, 'Mathematik' for de-abi).",
    )

    base_hours_per_year: dict[int, int] = Field(
        default_factory=dict,
        description="Map from target_year_index → base hours/year for this "
        "subject. Empty dict = same hours every year (use base_hours_default).",
    )
    base_hours_default: int | None = Field(
        default=None,
        ge=0,
        le=400,
        description="Default base hours/year if not specified per-year.",
    )
    advanced_hour_bonus: int = Field(
        default=27,
        ge=0,
        le=400,
        description="Hours added when the subject is taken at advanced level.",
    )

    optional: bool = Field(
        default=False,
        description="True if this subject is not required in every target year.",
    )

    def hours_for_year(self, target_year_index: int) -> int | None:
        """Effective base hours for a given target year."""
        if target_year_index in self.base_hours_per_year:
            return self.base_hours_per_year[target_year_index]
        return self.base_hours_default


class TargetSubjectTaxonomy(BaseModel):
    """Full mapping of canonical subjects to a target system's representation.

    Invariants:
    1. Every entry has a unique :class:`CanonicalSubjectId`.
    2. If ``base_hours_per_year`` is empty, ``base_hours_default`` MUST be
       present (otherwise hours are unknown and rendering breaks).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    entries: list[TargetSubjectEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        ids = [e.canonical_id for e in self.entries]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate canonical_id in target subject taxonomy")
        # OK to omit hours entirely if the subject is marked optional or
        # informational (no hour cell rendered).
        for e in self.entries:
            if not e.base_hours_per_year and e.base_hours_default is None and not e.optional:
                raise ValueError(
                    f"subject {e.canonical_id} requires either "
                    "base_hours_default or base_hours_per_year (or "
                    "must be marked optional=True)"
                )
        return self

    def for_canonical(self, canonical_id: CanonicalSubjectId) -> TargetSubjectEntry | None:
        for e in self.entries:
            if e.canonical_id == canonical_id:
                return e
        return None


__all__ = ["TargetSubjectEntry", "TargetSubjectTaxonomy"]

"""Target-side year system + source-canonical-to-target mapping."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TargetYearEntry(BaseModel):
    """One year on the target system's year scale.

    ``source_year_index`` is the index in the *source* education system
    that maps to this target year. The mapping is N-to-1 in general (e.g.,
    a target system might collapse two source years into a single target
    label) but is 1-to-1 for the standard PL → US-HS case.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    target_index: int = Field(ge=1, le=13)
    """1-based index in the target system."""

    source_year_index: int = Field(ge=1, le=12)
    """1-based source-system year that maps to this target year. The Polish
    profile produces 1..4 (pierwszej..czwartej) which the US-HS target maps
    to 9..12 with target_index = source_year_index + 8."""

    display_name: str = Field(min_length=1, max_length=64)
    """Display label, e.g., 'Grade 9', 'Year 11', 'Lower Sixth'."""


class TargetYearSystem(BaseModel):
    """Full target-side year system.

    Invariants:
    1. Every ``target_index`` is unique.
    2. ``source_year_index`` values are unique (1-to-1 mapping).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=500)
    entries: list[TargetYearEntry] = Field(min_length=1, max_length=13)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        targets = [e.target_index for e in self.entries]
        if len(set(targets)) != len(targets):
            raise ValueError("duplicate target_index in target year system")
        sources = [e.source_year_index for e in self.entries]
        if len(set(sources)) != len(sources):
            raise ValueError("duplicate source_year_index in target year system")
        return self

    def for_source_year(self, source_year_index: int) -> TargetYearEntry | None:
        for entry in self.entries:
            if entry.source_year_index == source_year_index:
                return entry
        return None


__all__ = ["TargetYearEntry", "TargetYearSystem"]

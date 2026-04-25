"""Source-side year/class naming system.

Maps source-language year names (PL: pierwszej, drugiej, ...; VN: lớp 10,
lớp 11, ...) to a canonical 1-based numeric year index.
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class YearSystemEntry(BaseModel):
    """One year/class in the source education system."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    index: int = Field(
        ge=1,
        le=12,
        description="1-based year index in this education system.",
    )
    raw_name: str = Field(
        min_length=1,
        max_length=64,
        description="Canonical raw name as it appears on transcripts.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Alternative spellings (case-fold matched).",
    )
    label: str = Field(
        min_length=1,
        max_length=64,
        description="Display label.",
    )


class ProfileYearSystem(BaseModel):
    """Year system definition for a source education system.

    Invariants:
    1. ``index`` values are unique and form a contiguous range 1..N.
    2. Names + aliases are globally unique across the system.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(
        min_length=1,
        max_length=64,
        description="Stable id (e.g., 'pl.lo.4year.v1').",
    )
    description: str | None = Field(default=None, max_length=500)
    promotes_to_next_year: bool = Field(
        default=True,
        description="True if a successful transcript implies promotion to "
        "the next year (= target_year_index = source_year_index + 1).",
    )
    entries: list[YearSystemEntry] = Field(
        min_length=1,
        max_length=12,
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        indices = [e.index for e in self.entries]
        if sorted(indices) != list(range(1, len(indices) + 1)):
            raise ValueError("year system entries must use a contiguous 1..N index range")

        seen: set[str] = set()
        for entry in self.entries:
            for token in (entry.raw_name, *entry.aliases):
                key = token.casefold().strip()
                if key in seen:
                    raise ValueError(f"duplicate year name / alias: {token!r}")
                seen.add(key)
        return self

    def lookup(self, raw_or_alias: str) -> YearSystemEntry | None:
        key = raw_or_alias.casefold().strip()
        for entry in self.entries:
            if entry.raw_name.casefold().strip() == key:
                return entry
            if any(a.casefold().strip() == key for a in entry.aliases):
                return entry
        return None


__all__ = ["ProfileYearSystem", "YearSystemEntry"]

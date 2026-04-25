"""Subject vocabulary for a source profile.

Maps source-language subject names (e.g., 'Matematyka') to canonical
subject ids (e.g., :attr:`CanonicalSubjectId.MATHEMATICS`).
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.enums.canonical import CanonicalSubjectId


class SubjectMapping(BaseModel):
    """Map one or more raw subject names to a canonical subject id."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    raw_name: str = Field(
        min_length=1,
        max_length=200,
        description="Canonical raw subject name (most common form).",
    )
    aliases: list[str] = Field(
        default_factory=list,
        max_length=10,
        description="Alternative spellings recognized as this subject.",
    )
    canonical_id: CanonicalSubjectId = Field(
        description="Target canonical id.",
    )
    notes: str | None = Field(
        default=None,
        max_length=500,
    )


class ProfileVocabulary(BaseModel):
    """All subject mappings for a source profile.

    Invariants:
    1. Every raw_name + alias is globally unique across the vocabulary.
    2. A single canonical_id may have multiple raw_name mappings (e.g.,
       'Język polski' and 'J. polski' both map to L1_NATIVE).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(
        min_length=1,
        max_length=64,
        description="Stable id (e.g., 'pl.lo.subjects.v1').",
    )
    description: str | None = Field(default=None, max_length=500)
    mappings: list[SubjectMapping] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _unique_names(self) -> Self:
        seen: set[str] = set()
        for m in self.mappings:
            for token in (m.raw_name, *m.aliases):
                key = token.casefold().strip()
                if key in seen:
                    raise ValueError(f"duplicate subject name / alias across vocabulary: {token!r}")
                seen.add(key)
        return self

    def lookup(self, raw_or_alias: str) -> SubjectMapping | None:
        key = raw_or_alias.casefold().strip()
        for m in self.mappings:
            if m.raw_name.casefold().strip() == key:
                return m
            if any(a.casefold().strip() == key for a in m.aliases):
                return m
        return None


__all__ = ["ProfileVocabulary", "SubjectMapping"]

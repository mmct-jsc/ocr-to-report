"""Declarative extraction schema for a source profile.

Drives the JSON Schema sent to the vision model. Each field declares its
type, whether it is required, its PII classification, and (optionally) a
validation regex. Phase 2 compiles this into a JSON Schema; Phase 3 sends
it to the vision adapter.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.pii.classes import PIIClass


class ExtractionFieldKind(StrEnum):
    """The structural shape of a field the vision model should produce."""

    STRING = "string"
    DATE = "date"
    INTEGER = "integer"
    BOOLEAN = "boolean"
    LIST_STRING = "list[string]"
    SUBJECT_TABLE = "subject_table"
    """A list of {raw_subject_name, raw_grade_value, notes} rows from the
    main grade table on the document."""
    ADVANCED_SUBJECTS = "advanced_subjects"
    """A list of raw subject names from the 'extended subjects' / advanced
    section, used to mark subjects[].is_advanced."""


class ExtractionField(BaseModel):
    """One field the vision model is asked to extract."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    name: str = Field(
        min_length=1,
        max_length=64,
        pattern=r"^[a-z][a-z0-9_]*$",
        description="Snake_case key under which the value appears in the extraction result.",
    )
    description: str = Field(
        min_length=1,
        max_length=500,
        description="Plain-English description shown to the vision model "
        "as the prompt for this field.",
    )
    kind: ExtractionFieldKind
    required: bool = Field(default=True)
    pii_class: PIIClass = Field(
        default=PIIClass.INTERNAL,
        description="PII classification — drives redaction in logs and audit metadata.",
    )
    validation_pattern: str | None = Field(
        default=None,
        max_length=300,
        description="Optional regex the value must satisfy "
        "(applies to STRING/DATE; ignored for other kinds).",
    )
    examples: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Up to 5 example values shown to the vision model.",
    )


class ProfileExtractionSchema(BaseModel):
    """Complete extraction schema for a source profile.

    Invariants:
    1. Every field name is unique.
    2. At least one field of kind ``SUBJECT_TABLE`` exists (transcripts
       must have grade rows to be useful — caught early instead of
       producing empty CanonicalTranscript objects).
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: str = Field(
        min_length=1,
        max_length=64,
        description="Stable id (e.g., 'pl.lo.swiadectwo_szkolne.extraction.v1').",
    )
    description: str | None = Field(default=None, max_length=500)
    fields: list[ExtractionField] = Field(min_length=2, max_length=100)

    @model_validator(mode="after")
    def _validate(self) -> Self:
        names = [f.name for f in self.fields]
        if len(set(names)) != len(names):
            raise ValueError("extraction schema field names must be unique")
        if not any(f.kind is ExtractionFieldKind.SUBJECT_TABLE for f in self.fields):
            raise ValueError("extraction schema must include at least one SUBJECT_TABLE field")
        return self


__all__ = [
    "ExtractionField",
    "ExtractionFieldKind",
    "ProfileExtractionSchema",
]

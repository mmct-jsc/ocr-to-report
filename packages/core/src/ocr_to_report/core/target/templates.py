"""Target-side template descriptors.

A template binds canonical fields to specific cells / placeholders in an
xlsx (or other) file. Per Decision 4, the template file itself is shipped
in ``targets/<id>/templates/<key>.xlsx``; this module describes the
*binding* between canonical data and template placeholders.

The actual rendering engine (openpyxl-based, Phase 4) consumes these
descriptors to fill the template.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.enums.canonical import CanonicalSubjectId


class TemplateBindingKind(StrEnum):
    """What part of the canonical record a template cell pulls from."""

    STUDENT_FULL_NAME = "student.full_name"
    STUDENT_BIRTH_DATE = "student.birth_date"
    STUDENT_SCHOOL_YEAR = "student.school_year"
    STUDENT_SCHOOL_NAME = "student.school_name"
    STUDENT_CITY = "student.city"
    STUDENT_REGION = "student.region"
    TARGET_YEAR_DISPLAY = "target.year_display"
    TARGET_NEXT_YEAR_DISPLAY = "target.next_year_display"
    SUBJECT_GRADE = "subject.grade"  # references subject by canonical_id
    SUBJECT_HOURS = "subject.hours"  # references subject by canonical_id
    CONDUCT_VALUE = "conduct.value"
    LITERAL = "literal"  # fixed string from `literal_value`


class TemplateCellBinding(BaseModel):
    """Binding for a single template cell.

    For ``SUBJECT_GRADE`` / ``SUBJECT_HOURS`` bindings, ``subject_id``
    must be set.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    cell: str = Field(
        pattern=r"^[A-Z]{1,3}\d{1,7}$",
        description="A1-style cell reference (e.g., 'A2', 'D19').",
    )
    kind: TemplateBindingKind
    subject_id: CanonicalSubjectId | None = Field(
        default=None,
        description="Required when kind is SUBJECT_GRADE or SUBJECT_HOURS.",
    )
    literal_value: str | None = Field(
        default=None,
        description="Required when kind is LITERAL.",
    )

    @model_validator(mode="after")
    def _validate(self) -> Self:
        needs_subject = {
            TemplateBindingKind.SUBJECT_GRADE,
            TemplateBindingKind.SUBJECT_HOURS,
        }
        if self.kind in needs_subject and self.subject_id is None:
            raise ValueError(f"binding kind {self.kind} requires subject_id")
        if self.kind not in needs_subject and self.subject_id is not None:
            raise ValueError(f"binding kind {self.kind} must not set subject_id")
        if self.kind is TemplateBindingKind.LITERAL and self.literal_value is None:
            raise ValueError("LITERAL binding requires literal_value")
        if self.kind is not TemplateBindingKind.LITERAL and self.literal_value is not None:
            raise ValueError("only LITERAL bindings may set literal_value")
        return self


class TargetTemplate(BaseModel):
    """Descriptor for a single output template."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    key: str = Field(
        pattern=r"^[a-z][a-z0-9_]*$",
        min_length=1,
        max_length=64,
        description="Template key (e.g., 'grade_9'), used to select among this target's templates.",
    )
    description: str | None = Field(default=None, max_length=500)
    blob_path: str = Field(
        min_length=1,
        max_length=300,
        description="Path within the target bundle directory to the template "
        "file, relative to the bundle root (e.g., 'templates/grade_9.xlsx').",
    )
    output_format: str = Field(
        pattern=r"^(xlsx|pdf|csv|docx|json)$",
        description="Output file format.",
    )
    target_year_index: int | None = Field(
        default=None,
        ge=1,
        le=13,
        description="Optional pin: this template is only valid for a "
        "specific target year. Renderer rejects mismatched bindings.",
    )
    bindings: list[TemplateCellBinding] = Field(
        min_length=1,
        max_length=500,
        description="Per-cell bindings used to fill the template.",
    )

    @model_validator(mode="after")
    def _unique_cells(self) -> Self:
        cells = [b.cell for b in self.bindings]
        if len(set(cells)) != len(cells):
            raise ValueError("template bindings reference the same cell more than once")
        return self


__all__ = [
    "TargetTemplate",
    "TemplateBindingKind",
    "TemplateCellBinding",
]

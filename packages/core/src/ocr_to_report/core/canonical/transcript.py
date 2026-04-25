"""Top-level canonical transcript — the universal IR."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ocr_to_report.core.canonical.conduct import CanonicalConduct
from ocr_to_report.core.canonical.grade import CanonicalGrade
from ocr_to_report.core.canonical.student import CanonicalStudent
from ocr_to_report.core.canonical.subject import CanonicalSubject
from ocr_to_report.core.pii.classes import PIIClass
from ocr_to_report.core.types import Confidence, ProfileId, SchemaVersion

CANONICAL_TRANSCRIPT_SCHEMA_VERSION: Literal["1.0"] = "1.0"


class CanonicalTranscript(BaseModel):
    """The result of source-profile extraction in language-neutral form.

    This is what every adapter produces and what every target system
    consumes. Adding a new source profile = code that produces this; adding
    a new target system = code that reads this.

    Invariants:
    1. ``overall_confidence`` ≤ ``min(subject.confidence for subject in
       subjects)`` if the list is non-empty, and ≤ ``student.confidence``,
       and ≤ ``conduct.confidence`` (if present), and ≤
       ``religion_ethics.confidence`` (if present). Confidence flows
       monotonically up.
    2. ``schema_version`` is a fixed literal — bumping it is a breaking
       change requiring a migration plan.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: SchemaVersion = Field(
        default=CANONICAL_TRANSCRIPT_SCHEMA_VERSION,
        description="Schema version of this canonical transcript.",
    )
    source_profile_id: ProfileId = Field(
        description="ID of the source profile bundle that produced this transcript.",
    )

    student: CanonicalStudent
    conduct: CanonicalConduct | None = Field(
        default=None,
        description="Conduct/zachowanie record, if extracted.",
    )

    # Religion / ethics is GDPR Article 9 sensitive data. It may only be
    # populated when the tenant has explicitly opted in. Profiles MUST omit
    # this field by default — see core/pii/classes.py for handling rules.
    religion_ethics: Annotated[CanonicalGrade | None, PIIClass.SENSITIVE] = Field(
        default=None,
        description="Religion/ethics grade. EXCLUDED by default; opt-in only.",
    )

    subjects: list[CanonicalSubject] = Field(
        default_factory=list,
        description="One row per academic subject on the transcript.",
    )
    advanced_raw_names: list[str] = Field(
        default_factory=list,
        description="Raw source-side names from the 'extended subjects' "
        "section, used for cross-validation against subjects[].is_advanced.",
    )

    overall_confidence: Confidence = Field(
        description="Aggregate confidence; ≤ min of all child confidences.",
    )
    extraction_warnings: list[str] = Field(
        default_factory=list,
        description="Non-fatal issues encountered during extraction "
        "(e.g., 'unrecognized subject: X', 'low confidence on field Y').",
    )

    @model_validator(mode="after")
    def _confidence_monotonic(self) -> Self:
        floors: list[float] = [self.student.confidence]
        if self.conduct is not None:
            floors.append(self.conduct.confidence)
        if self.religion_ethics is not None:
            floors.append(self.religion_ethics.confidence)
        floors.extend(subj.confidence for subj in self.subjects)
        if floors and self.overall_confidence > min(floors) + 1e-9:
            raise ValueError(
                f"overall_confidence {self.overall_confidence} exceeds the "
                f"minimum child confidence {min(floors)}; must flow upward"
            )
        return self


__all__ = ["CANONICAL_TRANSCRIPT_SCHEMA_VERSION", "CanonicalTranscript"]

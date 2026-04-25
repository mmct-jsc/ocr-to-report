"""Top-level container for a fully-loaded source profile bundle."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from ocr_to_report.core.profile.extraction_schema import ProfileExtractionSchema
from ocr_to_report.core.profile.grade_scale import ProfileGradeScale
from ocr_to_report.core.profile.manifest import ProfileManifest
from ocr_to_report.core.profile.vocabulary import ProfileVocabulary
from ocr_to_report.core.profile.year_system import ProfileYearSystem


class ProfileBundle(BaseModel):
    """Loaded, validated profile bundle ready for use by the pipeline.

    The :class:`ProfileRegistry` (Phase 2) reads YAML from
    ``profiles/<id>/`` and constructs one of these per profile.

    Invariants:
    1. ``manifest.id`` is the source of truth; sub-component ids are
       informational only.
    2. The conduct scale id and grade scale id may be the same physical
       object — they often differ (PL: grading is 6-point, conduct is its
       own scale). Both are required by every profile.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    manifest: ProfileManifest
    extraction_schema: ProfileExtractionSchema
    vocabulary: ProfileVocabulary
    grade_scale: ProfileGradeScale
    conduct_scale: ProfileGradeScale
    """Conduct uses a `ProfileGradeScale`-shaped object too — same shape,
    different vocabulary. We reuse the type rather than introducing
    a parallel one."""
    year_system: ProfileYearSystem

    extraction_prompt_template: str
    """Vision-model system prompt template (Markdown). Phase 3 fills in
    {schema_json} and {language_hint} before sending to the model."""

    @property
    def id(self) -> str:
        return self.manifest.id

    @model_validator(mode="after")
    def _validate(self) -> Self:
        # Sanity: prompt template should reference at least one of the
        # known interpolation slots so we know it's not a stale template.
        # The slots are documented in CONTRIBUTING_PROFILE.md (Phase 2).
        slots_present = any(
            s in self.extraction_prompt_template
            for s in ("{schema_json}", "{language_hint}", "{document_type}")
        )
        if not slots_present:
            raise ValueError(
                "extraction_prompt_template must reference at least one of "
                "{schema_json}, {language_hint}, {document_type}"
            )
        return self


__all__ = ["ProfileBundle"]

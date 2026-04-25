"""Top-level container for a fully-loaded target system bundle."""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, model_validator

from ocr_to_report.core.target.grade_scale import TargetGradeScale
from ocr_to_report.core.target.manifest import TargetManifest
from ocr_to_report.core.target.subject_taxonomy import TargetSubjectTaxonomy
from ocr_to_report.core.target.templates import TargetTemplate
from ocr_to_report.core.target.year_system import TargetYearSystem


class TargetBundle(BaseModel):
    """Loaded, validated target system bundle ready for use by the renderer.

    Invariants:
    1. ``manifest.id`` is the source of truth.
    2. Every template's ``output_format`` is in
       ``manifest.output_formats``.
    3. Template keys are unique across ``templates``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    manifest: TargetManifest
    grade_scale: TargetGradeScale
    year_system: TargetYearSystem
    subject_taxonomy: TargetSubjectTaxonomy
    conduct_scale: TargetGradeScale
    """Conduct uses the same shape as grade_scale; some target systems may
    not render conduct (then this scale's mapping is ignored by the
    renderer)."""

    templates: list[TargetTemplate]

    @property
    def id(self) -> str:
        return self.manifest.id

    @model_validator(mode="after")
    def _validate(self) -> Self:
        keys = [t.key for t in self.templates]
        if len(set(keys)) != len(keys):
            raise ValueError("template keys must be unique within a target bundle")

        for t in self.templates:
            if t.output_format not in self.manifest.output_formats:
                raise ValueError(
                    f"template {t.key} has output_format={t.output_format!r} "
                    f"not declared in manifest.output_formats="
                    f"{self.manifest.output_formats}"
                )
        return self

    def template_for_year(self, target_year_index: int) -> TargetTemplate | None:
        for t in self.templates:
            if t.target_year_index == target_year_index:
                return t
        return None


__all__ = ["TargetBundle"]

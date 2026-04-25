"""Target system schema types.

Defines the *shape* of a target bundle. Loader and renderer integration
are introduced in Phases 2 and 4 respectively.
"""

from ocr_to_report.core.target.bundle import TargetBundle
from ocr_to_report.core.target.grade_scale import (
    TargetGradeScale,
    TargetGradeScaleLevel,
)
from ocr_to_report.core.target.manifest import TargetManifest
from ocr_to_report.core.target.subject_taxonomy import (
    TargetSubjectEntry,
    TargetSubjectTaxonomy,
)
from ocr_to_report.core.target.templates import (
    TargetTemplate,
    TemplateBindingKind,
    TemplateCellBinding,
)
from ocr_to_report.core.target.year_system import (
    TargetYearEntry,
    TargetYearSystem,
)

__all__ = [
    "TargetBundle",
    "TargetGradeScale",
    "TargetGradeScaleLevel",
    "TargetManifest",
    "TargetSubjectEntry",
    "TargetSubjectTaxonomy",
    "TargetTemplate",
    "TargetYearEntry",
    "TargetYearSystem",
    "TemplateBindingKind",
    "TemplateCellBinding",
]

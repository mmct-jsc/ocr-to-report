"""Source profile schema types.

Defines the *shape* of a profile bundle. The loader, registry, and override
resolver are introduced in Phase 2 (``packages/core/src/ocr_to_report/
core/profiles/``). The Pydantic types here are pure data — no I/O.
"""

from ocr_to_report.core.profile.bundle import ProfileBundle
from ocr_to_report.core.profile.extraction_schema import (
    ExtractionField,
    ExtractionFieldKind,
    ProfileExtractionSchema,
)
from ocr_to_report.core.profile.grade_scale import (
    GradeScaleLevel,
    ProfileGradeScale,
)
from ocr_to_report.core.profile.manifest import (
    EducationSystemCode,
    LanguageCode,
    ProfileFingerprint,
    ProfileManifest,
)
from ocr_to_report.core.profile.vocabulary import (
    ProfileVocabulary,
    SubjectMapping,
)
from ocr_to_report.core.profile.year_system import (
    ProfileYearSystem,
    YearSystemEntry,
)

__all__ = [
    "EducationSystemCode",
    "ExtractionField",
    "ExtractionFieldKind",
    "GradeScaleLevel",
    "LanguageCode",
    "ProfileBundle",
    "ProfileExtractionSchema",
    "ProfileFingerprint",
    "ProfileGradeScale",
    "ProfileManifest",
    "ProfileVocabulary",
    "ProfileYearSystem",
    "SubjectMapping",
    "YearSystemEntry",
]

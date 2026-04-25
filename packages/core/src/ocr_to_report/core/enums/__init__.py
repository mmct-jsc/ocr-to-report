"""Enumerations used across the core domain.

Source-side (Polish, etc.) enums live in language-specific modules. Target-
side (us-hs, us-college, etc.) enums live in target-specific modules. The
language-neutral canonical enums live in :mod:`canonical`.
"""

from ocr_to_report.core.enums.canonical import (
    CanonicalConductLevel,
    CanonicalGradeLevel,
    CanonicalSubjectId,
)
from ocr_to_report.core.enums.polish import PolishClass, PolishConduct, PolishGrade
from ocr_to_report.core.enums.us import USGrade, USGradeYear

__all__ = [
    "CanonicalConductLevel",
    "CanonicalGradeLevel",
    "CanonicalSubjectId",
    "PolishClass",
    "PolishConduct",
    "PolishGrade",
    "USGrade",
    "USGradeYear",
]

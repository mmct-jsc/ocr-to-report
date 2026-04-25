"""Canonical (language-neutral) IR types.

Every source-profile extraction produces a :class:`CanonicalTranscript`;
every target-system rendering consumes one. The core invariant of the
five-axis schema-driven model: profiles know nothing about targets and
vice versa — they speak only this canonical IR.
"""

from ocr_to_report.core.canonical.conduct import CanonicalConduct
from ocr_to_report.core.canonical.grade import CanonicalGrade, categorical_for
from ocr_to_report.core.canonical.student import CanonicalStudent
from ocr_to_report.core.canonical.subject import (
    DEFAULT_ADVANCED_HOUR_BONUS,
    CanonicalSubject,
)
from ocr_to_report.core.canonical.transcript import (
    CANONICAL_TRANSCRIPT_SCHEMA_VERSION,
    CanonicalTranscript,
)

__all__ = [
    "CANONICAL_TRANSCRIPT_SCHEMA_VERSION",
    "DEFAULT_ADVANCED_HOUR_BONUS",
    "CanonicalConduct",
    "CanonicalGrade",
    "CanonicalStudent",
    "CanonicalSubject",
    "CanonicalTranscript",
    "categorical_for",
]

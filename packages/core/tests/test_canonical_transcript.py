"""CanonicalTranscript invariant tests."""

from __future__ import annotations

from datetime import date

import pytest

from ocr_to_report.core.canonical.conduct import CanonicalConduct
from ocr_to_report.core.canonical.grade import CanonicalGrade
from ocr_to_report.core.canonical.student import CanonicalStudent
from ocr_to_report.core.canonical.subject import CanonicalSubject
from ocr_to_report.core.canonical.transcript import (
    CANONICAL_TRANSCRIPT_SCHEMA_VERSION,
    CanonicalTranscript,
)
from ocr_to_report.core.enums.canonical import CanonicalConductLevel, CanonicalSubjectId


def _student(confidence: float = 1.0) -> CanonicalStudent:
    return CanonicalStudent(
        full_name="Antoni Judek",
        birth_date=date(2009, 12, 21),
        school_year="2023/2024",
        source_year_index=1,
        target_year_index=2,
        promoted=True,
        school_name="Spark Academy",
        city="Poznań",
        region="wielkopolskie",
        confidence=confidence,
    )


def _grade(confidence: float = 1.0) -> CanonicalGrade:
    return CanonicalGrade.from_normalized(
        4 / 6,
        raw_source_value="bardzo dobry",
        raw_source_scale_id="pl.6point.v1",
        confidence=confidence,
    )


def _subject(
    confidence: float = 1.0, sid: CanonicalSubjectId = CanonicalSubjectId.MATHEMATICS
) -> CanonicalSubject:
    return CanonicalSubject(
        canonical_id=sid,
        raw_source_name=str(sid),
        grade=_grade(confidence),
        base_hours=108,
        confidence=confidence,
    )


def test_transcript_minimal() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject()],
        overall_confidence=0.9,
    )
    assert t.schema_version == CANONICAL_TRANSCRIPT_SCHEMA_VERSION
    assert len(t.subjects) == 1


def test_overall_confidence_must_not_exceed_minimum_child() -> None:
    # subject has confidence 0.5 → overall_confidence must be ≤ 0.5
    with pytest.raises(ValueError):
        CanonicalTranscript(
            source_profile_id="pl.lo.swiadectwo_szkolne.v1",
            student=_student(),
            subjects=[_subject(confidence=0.5)],
            overall_confidence=0.7,
        )


def test_overall_confidence_at_minimum_ok() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject(confidence=0.5), _subject(confidence=0.8)],
        overall_confidence=0.5,
    )
    assert t.overall_confidence == 0.5


def test_overall_confidence_with_conduct_floor() -> None:
    conduct = CanonicalConduct(
        level=CanonicalConductLevel.EXEMPLARY,
        raw_source_value="wzorowe",
        confidence=0.6,
    )
    with pytest.raises(ValueError):
        CanonicalTranscript(
            source_profile_id="pl.lo.swiadectwo_szkolne.v1",
            student=_student(),
            conduct=conduct,
            subjects=[_subject(confidence=0.9)],
            overall_confidence=0.8,  # exceeds conduct's 0.6
        )


def test_religion_ethics_default_excluded() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject()],
        overall_confidence=0.95,
    )
    assert t.religion_ethics is None


def test_extraction_warnings_optional() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject()],
        overall_confidence=0.95,
        extraction_warnings=["unknown subject 'Filozofia'"],
    )
    assert t.extraction_warnings == ["unknown subject 'Filozofia'"]


def test_advanced_raw_names_default_empty() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject()],
        overall_confidence=0.95,
    )
    assert t.advanced_raw_names == []


def test_transcript_is_frozen() -> None:
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=_student(),
        subjects=[_subject()],
        overall_confidence=0.95,
    )
    with pytest.raises(ValueError):
        t.overall_confidence = 0.5  # type: ignore[misc]

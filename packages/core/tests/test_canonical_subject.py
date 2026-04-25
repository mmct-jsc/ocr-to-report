"""CanonicalSubject invariant tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.canonical.grade import CanonicalGrade
from ocr_to_report.core.canonical.subject import (
    DEFAULT_ADVANCED_HOUR_BONUS,
    CanonicalSubject,
)
from ocr_to_report.core.enums.canonical import CanonicalSubjectId


def _make_grade(confidence: float = 1.0) -> CanonicalGrade:
    return CanonicalGrade.from_normalized(
        4 / 6,
        raw_source_value="bardzo dobry",
        raw_source_scale_id="pl.6point.v1",
        confidence=confidence,
    )


def test_total_hours_with_advanced_adds_bonus() -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=_make_grade(),
        base_hours=108,
        is_advanced=True,
    )
    assert s.total_hours == 108 + DEFAULT_ADVANCED_HOUR_BONUS


def test_total_hours_without_advanced() -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=_make_grade(),
        base_hours=108,
        is_advanced=False,
    )
    assert s.total_hours == 108


def test_total_hours_with_custom_bonus() -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=_make_grade(),
        base_hours=100,
        is_advanced=True,
        advanced_hour_bonus=50,
    )
    assert s.total_hours == 150


def test_total_hours_none_when_base_unknown() -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=_make_grade(),
        base_hours=None,
    )
    assert s.total_hours is None


def test_row_confidence_cannot_exceed_grade_confidence() -> None:
    g = _make_grade(confidence=0.7)
    with pytest.raises(ValueError):
        CanonicalSubject(
            canonical_id=CanonicalSubjectId.MATHEMATICS,
            raw_source_name="Matematyka",
            grade=g,
            base_hours=108,
            confidence=0.9,
        )


def test_unrecognized_subject_canonical_id_none() -> None:
    s = CanonicalSubject(
        canonical_id=None,
        raw_source_name="Klub szachowy",
        grade=None,
        confidence=0.5,
    )
    assert s.canonical_id is None
    assert s.confidence == 0.5
    assert s.total_hours is None


def test_subject_is_frozen() -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="Matematyka",
        grade=None,
    )
    with pytest.raises(ValueError):
        s.is_advanced = True  # type: ignore[misc]


def test_base_hours_negative_rejected() -> None:
    with pytest.raises(ValueError):
        CanonicalSubject(
            canonical_id=CanonicalSubjectId.MATHEMATICS,
            raw_source_name="Matematyka",
            base_hours=-1,
        )


def test_base_hours_unrealistic_rejected() -> None:
    with pytest.raises(ValueError):
        CanonicalSubject(
            canonical_id=CanonicalSubjectId.MATHEMATICS,
            raw_source_name="Matematyka",
            base_hours=10_000,
        )

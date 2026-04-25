"""Property-based invariant tests via hypothesis.

These exercise the structural invariants of canonical types over the full
input space, catching edge cases example-based tests miss.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Annotated

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import BaseModel

from ocr_to_report.core.canonical.grade import CanonicalGrade, categorical_for
from ocr_to_report.core.canonical.student import CanonicalStudent
from ocr_to_report.core.canonical.subject import CanonicalSubject
from ocr_to_report.core.canonical.transcript import CanonicalTranscript
from ocr_to_report.core.enums.canonical import CanonicalGradeLevel, CanonicalSubjectId
from ocr_to_report.core.enums.polish import PolishClass, PolishGrade
from ocr_to_report.core.pii import PIIClass, redact_log_event

pytestmark = pytest.mark.property


# ─── CanonicalGrade roundtrip ──────────────────────────────────
@given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_canonical_grade_categorical_round_trip(score: float) -> None:
    """For any score in [0,1], from_normalized constructs a valid grade
    whose categorical level matches the score."""
    g = CanonicalGrade.from_normalized(
        score,
        raw_source_value="x",
        raw_source_scale_id="t.v1",
    )
    assert g.level_categorical == categorical_for(score)
    assert 0.0 <= g.level_normalized <= 1.0


@given(score=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False))
def test_canonical_grade_serialization_round_trip(score: float) -> None:
    g = CanonicalGrade.from_normalized(
        score,
        raw_source_value="abc",
        raw_source_scale_id="t.v1",
    )
    assert CanonicalGrade(**g.model_dump()) == g


# ─── Polish grade ↔ word round trip ────────────────────────────
@given(g=st.sampled_from(list(PolishGrade)))
def test_polish_grade_word_unique_per_grade(g: PolishGrade) -> None:
    word = g.polish_word
    matches = [other for other in PolishGrade if other.polish_word == word]
    assert matches == [g]


# ─── Polish class ↔ index round trip ───────────────────────────
@given(idx=st.integers(min_value=1, max_value=4))
def test_polish_class_index_round_trip(idx: int) -> None:
    cls = PolishClass.from_index(idx)
    assert cls.to_index() == idx


# ─── Hours invariant ───────────────────────────────────────────
@given(
    base=st.integers(min_value=0, max_value=400),
    is_advanced=st.booleans(),
    bonus=st.integers(min_value=0, max_value=400),
)
def test_total_hours_formula(base: int, is_advanced: bool, bonus: int) -> None:
    s = CanonicalSubject(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        raw_source_name="X",
        base_hours=base,
        is_advanced=is_advanced,
        advanced_hour_bonus=bonus,
    )
    expected = base + (bonus if is_advanced else 0)
    assert s.total_hours == expected


# ─── Year derivation ───────────────────────────────────────────
@given(
    src=st.integers(min_value=1, max_value=11),
    promoted=st.booleans(),
)
def test_target_year_derivation(src: int, promoted: bool) -> None:
    target = src + (1 if promoted else 0)
    s = CanonicalStudent(
        full_name="Test Student",
        birth_date=date(2010, 1, 1),
        school_year="2023/2024",
        source_year_index=src,
        target_year_index=target,
        promoted=promoted,
        school_name="Some School",
    )
    assert s.target_year_index == target


@given(
    src=st.integers(min_value=1, max_value=11),
    target=st.integers(min_value=1, max_value=13),
    promoted=st.booleans(),
)
def test_inconsistent_target_rejected(src: int, target: int, promoted: bool) -> None:
    expected = src + (1 if promoted else 0)
    if target == expected:
        return  # consistent — not testing here
    with pytest.raises(ValueError):
        CanonicalStudent(
            full_name="Test",
            birth_date=date(2010, 1, 1),
            school_year="2023/2024",
            source_year_index=src,
            target_year_index=target,
            promoted=promoted,
            school_name="School",
        )


# ─── Confidence monotonic ──────────────────────────────────────
@settings(max_examples=50)
@given(
    student_conf=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    subject_confs=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
        min_size=1,
        max_size=20,
    ),
)
def test_overall_confidence_must_be_at_most_min_child(
    student_conf: float, subject_confs: list[float]
) -> None:
    # Build subjects with grades that satisfy the row-vs-grade invariant
    subjects = [
        CanonicalSubject(
            canonical_id=CanonicalSubjectId.MATHEMATICS,
            raw_source_name=f"S{i}",
            grade=CanonicalGrade.from_normalized(
                0.5,
                raw_source_value="x",
                raw_source_scale_id="t.v1",
                confidence=c,
            ),
            base_hours=10,
            confidence=c,
        )
        for i, c in enumerate(subject_confs)
    ]
    student = CanonicalStudent(
        full_name="Test",
        birth_date=date(2010, 1, 1),
        school_year="2023/2024",
        source_year_index=1,
        target_year_index=2,
        promoted=True,
        school_name="School",
        confidence=student_conf,
    )
    floor = min(student_conf, *subject_confs)

    # Construction at the floor should succeed
    t = CanonicalTranscript(
        source_profile_id="pl.lo.swiadectwo_szkolne.v1",
        student=student,
        subjects=subjects,
        overall_confidence=floor,
    )
    assert t.overall_confidence == floor

    # Construction strictly above the floor should fail when there is
    # meaningful headroom. The validator allows a 1e-9 fuzz; only test
    # rejection when above-floor exceeds that tolerance comfortably.
    above_floor = min(floor + 0.5, 1.0)
    if above_floor - floor > 1e-6:
        with pytest.raises(ValueError):
            CanonicalTranscript(
                source_profile_id="pl.lo.swiadectwo_szkolne.v1",
                student=student,
                subjects=subjects,
                overall_confidence=above_floor,
            )


# ─── PII redaction completeness ────────────────────────────────
class _PIIModel(BaseModel):
    name: Annotated[str, PIIClass.PII_DIRECT]
    school: Annotated[str, PIIClass.PII_QUASI]
    grade_note: Annotated[str, PIIClass.EDUCATIONAL]
    public_id: str


@given(
    name=st.text(min_size=1, max_size=80),
    school=st.text(min_size=1, max_size=80),
    grade_note=st.text(min_size=1, max_size=80),
)
def test_pii_values_never_appear_in_log_output(name: str, school: str, grade_note: str) -> None:
    """For arbitrary PII values, the redacted JSON must not contain them
    verbatim."""
    m = _PIIModel(name=name, school=school, grade_note=grade_note, public_id="pid")
    out = redact_log_event(None, "info", {"transcript": m})
    serialized = json.dumps(out, default=str)
    # Skip pathological short values that might trivially appear elsewhere
    # (e.g., name='a' could match by coincidence in field markers). Test only
    # the substantive case:
    if len(name) >= 3:
        assert name not in serialized
    if len(school) >= 3:
        assert school not in serialized
    if len(grade_note) >= 3:
        assert grade_note not in serialized


# ─── Canonical level coverage ──────────────────────────────────
@given(level=st.sampled_from(list(CanonicalGradeLevel)))
def test_categorical_for_inverse_within_band(level: CanonicalGradeLevel) -> None:
    """Picking the lower bound of any level must yield that level."""
    from ocr_to_report.core.canonical.grade import _LEVEL_LOWER_BOUNDS  # noqa: PLC0415

    assert categorical_for(_LEVEL_LOWER_BOUNDS[level]) is level

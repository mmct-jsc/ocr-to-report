"""CanonicalGrade tests including invariant enforcement."""

from __future__ import annotations

import pytest

from ocr_to_report.core.canonical.grade import CanonicalGrade, categorical_for
from ocr_to_report.core.enums.canonical import CanonicalGradeLevel


# ─── categorical_for ───────────────────────────────────────────
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.0, CanonicalGradeLevel.FAIL),
        (1 / 12, CanonicalGradeLevel.FAIL),
        (1 / 6, CanonicalGradeLevel.PASS),
        (2 / 6, CanonicalGradeLevel.SATISFACTORY),
        (3 / 6, CanonicalGradeLevel.GOOD),
        (4 / 6, CanonicalGradeLevel.VERY_GOOD),
        (5 / 6, CanonicalGradeLevel.EXCELLENT),
        (1.0, CanonicalGradeLevel.EXCELLENT),
    ],
)
def test_categorical_for_known_boundaries(score: float, expected: CanonicalGradeLevel) -> None:
    assert categorical_for(score) is expected


@pytest.mark.parametrize("score", [-0.01, 1.01, -10.0, 100.0])
def test_categorical_for_rejects_out_of_range(score: float) -> None:
    with pytest.raises(ValueError):
        categorical_for(score)


# ─── CanonicalGrade invariants ─────────────────────────────────
def test_canonical_grade_constructed_from_normalized() -> None:
    g = CanonicalGrade.from_normalized(
        4 / 6,
        raw_source_value="bardzo dobry",
        raw_source_scale_id="pl.6point.v1",
    )
    assert g.level_categorical is CanonicalGradeLevel.VERY_GOOD
    assert g.confidence == 1.0


def test_canonical_grade_inconsistent_categorical_rejected() -> None:
    with pytest.raises(ValueError):
        CanonicalGrade(
            level_normalized=4 / 6,
            level_categorical=CanonicalGradeLevel.FAIL,  # wrong band
            raw_source_value="bardzo dobry",
            raw_source_scale_id="pl.6point.v1",
        )


def test_canonical_grade_rejects_out_of_range_normalized() -> None:
    with pytest.raises(ValueError):
        CanonicalGrade(
            level_normalized=1.5,
            level_categorical=CanonicalGradeLevel.EXCELLENT,
            raw_source_value="x",
            raw_source_scale_id="pl.6point.v1",
        )


def test_canonical_grade_is_frozen() -> None:
    g = CanonicalGrade.from_normalized(
        0.5,
        raw_source_value="dobry",
        raw_source_scale_id="pl.6point.v1",
    )
    with pytest.raises(ValueError):
        g.level_normalized = 0.7  # type: ignore[misc]


def test_canonical_grade_confidence_bounds() -> None:
    with pytest.raises(ValueError):
        CanonicalGrade.from_normalized(
            0.5,
            raw_source_value="dobry",
            raw_source_scale_id="pl.6point.v1",
            confidence=1.5,
        )
    with pytest.raises(ValueError):
        CanonicalGrade.from_normalized(
            0.5,
            raw_source_value="dobry",
            raw_source_scale_id="pl.6point.v1",
            confidence=-0.1,
        )


def test_canonical_grade_serialization_round_trip() -> None:
    g = CanonicalGrade.from_normalized(
        2 / 6 + 0.01,
        raw_source_value="dostateczny",
        raw_source_scale_id="pl.6point.v1",
    )
    data = g.model_dump()
    restored = CanonicalGrade(**data)
    assert restored == g

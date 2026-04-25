"""CanonicalStudent invariant tests."""

from __future__ import annotations

from datetime import date

import pytest

from ocr_to_report.core.canonical.student import CanonicalStudent


def _kwargs(**over: object) -> dict[str, object]:
    base = {
        "full_name": "Antoni Judek",
        "birth_date": date(2009, 12, 21),
        "school_year": "2023/2024",
        "source_year_index": 1,
        "target_year_index": 2,
        "promoted": True,
        "promoted_with_distinction": True,
        "school_name": "Spark Academy",
        "city": "Poznań",
        "region": "wielkopolskie",
    }
    base.update(over)
    return base


def test_minimal_valid_student() -> None:
    s = CanonicalStudent(**_kwargs())  # type: ignore[arg-type]
    assert s.full_name == "Antoni Judek"
    assert s.target_year_index == 2


@pytest.mark.parametrize(
    "school_year",
    ["2023-2024", "23/24", "2023", "2023/2025", "abcd/efgh", "2023/2024 ", " 2023/2024"],
)
def test_invalid_school_year_format(school_year: str) -> None:
    with pytest.raises(ValueError):
        CanonicalStudent(**_kwargs(school_year=school_year))  # type: ignore[arg-type]


def test_school_year_second_must_follow_first() -> None:
    with pytest.raises(ValueError):
        CanonicalStudent(**_kwargs(school_year="2023/2025"))  # type: ignore[arg-type]


def test_target_year_index_promoted_consistency() -> None:
    # promoted=True with target=source → fail
    with pytest.raises(ValueError):
        CanonicalStudent(
            **_kwargs(source_year_index=2, target_year_index=2, promoted=True),  # type: ignore[arg-type]
        )


def test_target_year_index_not_promoted_consistency() -> None:
    # promoted=False with target=source+1 → fail
    with pytest.raises(ValueError):
        CanonicalStudent(
            **_kwargs(source_year_index=2, target_year_index=3, promoted=False),  # type: ignore[arg-type]
        )


def test_not_promoted_repeats_year() -> None:
    s = CanonicalStudent(
        **_kwargs(source_year_index=2, target_year_index=2, promoted=False),  # type: ignore[arg-type]
    )
    assert s.target_year_index == 2


def test_birth_date_optional() -> None:
    s = CanonicalStudent(**_kwargs(birth_date=None))  # type: ignore[arg-type]
    assert s.birth_date is None


def test_student_is_frozen() -> None:
    s = CanonicalStudent(**_kwargs())  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        s.full_name = "Other"  # type: ignore[misc]

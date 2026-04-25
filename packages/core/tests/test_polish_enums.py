"""Polish education-system enum tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.enums.polish import PolishClass, PolishConduct, PolishGrade


@pytest.mark.parametrize(
    ("idx", "expected"),
    [
        (1, PolishClass.PIERWSZEJ),
        (2, PolishClass.DRUGIEJ),
        (3, PolishClass.TRZECIEJ),
        (4, PolishClass.CZWARTEJ),
    ],
)
def test_polish_class_from_index(idx: int, expected: PolishClass) -> None:
    assert PolishClass.from_index(idx) is expected


@pytest.mark.parametrize("idx", [0, -1, 5, 100])
def test_polish_class_from_index_out_of_range(idx: int) -> None:
    with pytest.raises(ValueError):
        PolishClass.from_index(idx)


def test_polish_class_index_round_trip() -> None:
    for cls in PolishClass:
        assert PolishClass.from_index(cls.to_index()) is cls


@pytest.mark.parametrize(
    ("cls", "expected_next"),
    [
        (PolishClass.PIERWSZEJ, PolishClass.DRUGIEJ),
        (PolishClass.DRUGIEJ, PolishClass.TRZECIEJ),
        (PolishClass.TRZECIEJ, PolishClass.CZWARTEJ),
        (PolishClass.CZWARTEJ, None),
    ],
)
def test_polish_class_next(cls: PolishClass, expected_next: PolishClass | None) -> None:
    assert cls.next() == expected_next


def test_polish_grade_polish_word_round_trip() -> None:
    for g in PolishGrade:
        assert g.polish_word.strip() != ""


@pytest.mark.parametrize(
    ("g", "expected"),
    [
        (PolishGrade.NIEDOSTATECZNY, "niedostateczny"),
        (PolishGrade.DOPUSZCZAJACY, "dopuszczający"),
        (PolishGrade.DOSTATECZNY, "dostateczny"),
        (PolishGrade.DOBRY, "dobry"),
        (PolishGrade.BARDZO_DOBRY, "bardzo dobry"),
        (PolishGrade.CELUJACY, "celujący"),
    ],
)
def test_polish_grade_specific_words(g: PolishGrade, expected: str) -> None:
    assert g.polish_word == expected


@pytest.mark.parametrize(
    ("g", "passes"),
    [
        (PolishGrade.NIEDOSTATECZNY, False),
        (PolishGrade.DOPUSZCZAJACY, True),
        (PolishGrade.DOSTATECZNY, True),
        (PolishGrade.DOBRY, True),
        (PolishGrade.BARDZO_DOBRY, True),
        (PolishGrade.CELUJACY, True),
    ],
)
def test_polish_grade_is_passing(g: PolishGrade, passes: bool) -> None:
    assert g.is_passing() is passes


def test_polish_grade_ordering() -> None:
    grades = list(PolishGrade)
    assert sorted(grades) == grades  # IntEnum sorts by numeric value


def test_polish_conduct_distinct_from_grade() -> None:
    """PolishConduct uses a different vocabulary than PolishGrade."""
    grade_words = {g.polish_word.casefold() for g in PolishGrade}
    conduct_words = {c.value.casefold() for c in PolishConduct}
    assert grade_words.isdisjoint(conduct_words)

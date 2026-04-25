"""US high-school education-system enumerations.

Used by the ``us-hs.v1`` target system bundle. Other US targets (us-college,
us-gpa) live in their own bundles with their own enums.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class USGradeYear(IntEnum):
    """US high-school grade year (9..12).

    Mapping from :class:`PolishClass` is performed by mapping rules in the
    Polish source profile, not in core code, so this enum is independent.
    """

    GRADE_9 = 9
    GRADE_10 = 10
    GRADE_11 = 11
    GRADE_12 = 12

    @property
    def display_name(self) -> str:
        """Human-readable form used in reports: 'Grade 9', etc."""
        return f"Grade {self.value}"


class USGrade(StrEnum):
    """US letter grade scale used by the ``us-hs.v1`` target.

    Order is best → worst. Note: ``D_E`` represents the combined "D-E"
    letter the template uses for the lowest passing band (Polish
    *dopuszczający*).
    """

    A_PLUS = "A+"
    A = "A"
    B = "B"
    C = "C"
    D_E = "D-E"
    F = "F"

    @property
    def display_name(self) -> str:
        """The letter as it appears on the report."""
        return self.value


__all__ = ["USGrade", "USGradeYear"]

"""Language-neutral canonical enumerations.

Every source profile translates *into* and every target system translates
*out of* these. This is the universal IR — adding a new source language or
new target system never requires changes here.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class CanonicalGradeLevel(IntEnum):
    """Universal 6-level achievement scale (best at top, ordered ascending).

    All source-side grade scales map *into* this; all target-side scales
    map *out of* this. Numeric values exist purely so ordering is obvious;
    callers should compare via ``>=`` etc., not assume any particular
    spacing.
    """

    FAIL = 0
    PASS = 1
    SATISFACTORY = 2
    GOOD = 3
    VERY_GOOD = 4
    EXCELLENT = 5

    @property
    def display_name(self) -> str:
        return {
            CanonicalGradeLevel.FAIL: "Fail",
            CanonicalGradeLevel.PASS: "Pass",
            CanonicalGradeLevel.SATISFACTORY: "Satisfactory",
            CanonicalGradeLevel.GOOD: "Good",
            CanonicalGradeLevel.VERY_GOOD: "Very Good",
            CanonicalGradeLevel.EXCELLENT: "Excellent",
        }[self]


class CanonicalConductLevel(IntEnum):
    """Universal 6-level conduct scale (best at top).

    Distinct from :class:`CanonicalGradeLevel` because conduct is a
    behavioral assessment with a different vocabulary in most education
    systems.
    """

    REPREHENSIBLE = 0  # naganne (PL)
    INAPPROPRIATE = 1  # nieodpowiednie (PL)
    ACCEPTABLE = 2  # poprawne (PL)
    GOOD = 3  # dobre (PL)
    VERY_GOOD = 4  # bardzo dobre (PL)
    EXEMPLARY = 5  # wzorowe (PL)


class CanonicalSubjectId(StrEnum):
    """Canonical subject identifiers, ISCED-aligned where possible.

    Profiles map their localized subject names (e.g., "Matematyka",
    "Toán", "Mathématiques") to one of these. Targets map *back* to their
    own display strings (e.g., "Mathematics" for us-hs).

    The naming convention is uppercase-snake; new subjects added to this
    enum are non-breaking changes (existing profile/target bundles are
    unaffected unless they explicitly opt in).
    """

    # ─── Languages ─────────────────────────────────
    L1_NATIVE = "L1_NATIVE"  # The country's primary language (Polish for PL)
    L2_ENGLISH = "L2_ENGLISH"
    L2_GERMAN = "L2_GERMAN"
    L2_FRENCH = "L2_FRENCH"
    L2_SPANISH = "L2_SPANISH"
    L2_RUSSIAN = "L2_RUSSIAN"
    L2_OTHER = "L2_OTHER"
    LATIN_ANCIENT_CULTURE = "LATIN_ANCIENT_CULTURE"

    # ─── Humanities ────────────────────────────────
    HISTORY = "HISTORY"
    HISTORY_AND_PRESENT = "HISTORY_AND_PRESENT"  # PL: Historia i teraźniejszość
    SOCIAL_STUDIES = "SOCIAL_STUDIES"
    PHILOSOPHY = "PHILOSOPHY"
    GEOGRAPHY = "GEOGRAPHY"
    RELIGION_ETHICS = "RELIGION_ETHICS"

    # ─── STEM ──────────────────────────────────────
    MATHEMATICS = "MATHEMATICS"
    PHYSICS = "PHYSICS"
    CHEMISTRY = "CHEMISTRY"
    BIOLOGY = "BIOLOGY"
    INFORMATION_TECHNOLOGY = "INFORMATION_TECHNOLOGY"

    # ─── Arts ──────────────────────────────────────
    ART = "ART"
    MUSIC = "MUSIC"

    # ─── Other ─────────────────────────────────────
    PHYSICAL_EDUCATION = "PHYSICAL_EDUCATION"
    # PL: Edukacja dla bezpieczeństwa
    SAFETY_EDUCATION = "SAFETY_EDUCATION"
    # PL: Biznes i zarządzanie / Podstawy przedsiębiorczości
    ENTREPRENEURSHIP = "ENTREPRENEURSHIP"
    # explicit unknown bucket
    OTHER = "OTHER"

    @property
    def is_language(self) -> bool:
        return (
            self.value.startswith(("L1_", "L2_"))
            or self == CanonicalSubjectId.LATIN_ANCIENT_CULTURE
        )


__all__ = ["CanonicalConductLevel", "CanonicalGradeLevel", "CanonicalSubjectId"]

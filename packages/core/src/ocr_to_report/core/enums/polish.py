"""Polish education-system enumerations.

Source: Polish Ministry of National Education (MEN) standardized grading
scale and high-school year naming. Used by the
``pl.lo.swiadectwo_szkolne.v1`` source profile.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class PolishClass(StrEnum):
    """Polish 4-year liceum (high school) class names.

    The transcript field "do klasy <X>" indicates the class the student is
    being **promoted to**, while "uczęszczał do klasy <Y>" indicates the
    class they attended. The first profile in MVP looks at the *current*
    class (Y); promotion to next class is derived.
    """

    PIERWSZEJ = "pierwszej"
    """1st year (PL HS Year 1) — equivalent to US grade 9."""

    DRUGIEJ = "drugiej"
    """2nd year — US grade 10."""

    TRZECIEJ = "trzeciej"
    """3rd year — US grade 11."""

    CZWARTEJ = "czwartej"
    """4th year — US grade 12."""

    @classmethod
    def from_index(cls, idx: int) -> PolishClass:
        """idx 1..4 → corresponding PolishClass; raises ValueError otherwise."""
        mapping = {1: cls.PIERWSZEJ, 2: cls.DRUGIEJ, 3: cls.TRZECIEJ, 4: cls.CZWARTEJ}
        try:
            return mapping[idx]
        except KeyError as e:
            raise ValueError(f"Polish class index must be 1..4, got {idx}") from e

    def to_index(self) -> int:
        """Return 1..4 corresponding to this class."""
        return {
            PolishClass.PIERWSZEJ: 1,
            PolishClass.DRUGIEJ: 2,
            PolishClass.TRZECIEJ: 3,
            PolishClass.CZWARTEJ: 4,
        }[self]

    def next(self) -> PolishClass | None:
        """Return the class after this one, or None for CZWARTEJ (graduation)."""
        idx = self.to_index()
        return PolishClass.from_index(idx + 1) if idx < 4 else None


class PolishGrade(IntEnum):
    """Polish 6-point grading scale (Skala ocen — *zajęcia edukacyjne*).

    Lower numeric value = lower achievement. 1 is failing; 2 is the lowest
    pass; 6 is excellent. This scale is distinct from the *zachowanie*
    (conduct) scale — see :class:`PolishConduct`.
    """

    NIEDOSTATECZNY = 1
    """Insufficient — fail. → US F."""

    DOPUSZCZAJACY = 2
    """Pass (lowest passing grade). → US D-E."""

    DOSTATECZNY = 3
    """Satisfactory. → US C."""

    DOBRY = 4
    """Good. → US B."""

    BARDZO_DOBRY = 5
    """Very good. → US A."""

    CELUJACY = 6
    """Excellent (top of scale). → US A+."""

    @property
    def polish_word(self) -> str:
        """The lowercase Polish adjective form, as it appears on transcripts."""
        return _POLISH_GRADE_WORDS[self]

    def is_passing(self) -> bool:
        return self.value >= 2


_POLISH_GRADE_WORDS: dict[PolishGrade, str] = {
    PolishGrade.NIEDOSTATECZNY: "niedostateczny",
    PolishGrade.DOPUSZCZAJACY: "dopuszczający",
    PolishGrade.DOSTATECZNY: "dostateczny",
    PolishGrade.DOBRY: "dobry",
    PolishGrade.BARDZO_DOBRY: "bardzo dobry",
    PolishGrade.CELUJACY: "celujący",
}


class PolishConduct(StrEnum):
    """Polish *zachowanie* (conduct) scale. **Distinct from grading scale.**

    Order from best to worst.
    """

    WZOROWE = "wzorowe"  # exemplary
    BARDZO_DOBRE = "bardzo dobre"  # very good
    DOBRE = "dobre"  # good
    POPRAWNE = "poprawne"  # correct / acceptable
    NIEODPOWIEDNIE = "nieodpowiednie"  # inappropriate
    NAGANNE = "naganne"  # reprehensible


__all__ = ["PolishClass", "PolishConduct", "PolishGrade"]

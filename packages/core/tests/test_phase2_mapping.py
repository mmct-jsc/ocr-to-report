"""Phase 2 — end-to-end mapping snapshot tests.

Synthetic Polish raw extraction → CanonicalTranscript → US-HS render data.
The fixture data mirrors the structure of a real ŚWIADECTWO SZKOLNE for a
Polish liceum 1st-year (US grade 9) student, with all PII anonymized to
fictional values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ocr_to_report.core.enums.canonical import (
    CanonicalConductLevel,
    CanonicalGradeLevel,
    CanonicalSubjectId,
)
from ocr_to_report.core.errors.domain import MappingError
from ocr_to_report.core.mapping import (
    canonical_to_render_data,
    extract_to_canonical,
)
from ocr_to_report.core.profiles import load_profile_bundle
from ocr_to_report.core.targets import load_target_bundle

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def polish_profile():
    return load_profile_bundle(REPO_ROOT / "profiles" / "pl.lo.swiadectwo_szkolne.v1")


@pytest.fixture(scope="module")
def us_hs_target():
    return load_target_bundle(REPO_ROOT / "targets" / "us-hs.v1")


def _anonymized_polish_grade9_extraction() -> dict[str, Any]:
    """Return an anonymized raw extraction approximating a real Polish
    liceum 1st-year transcript. Names and dates are fictional."""
    return {
        "full_name": "Jan Kowalski",
        "birth_date": "2010-01-15",
        "school_year": "2023/2024",
        "current_class_name": "pierwszej",
        "school_name": "Test Academy LO",
        "city": "Warszawa",
        "region": "mazowieckie",
        "promoted": True,
        "promoted_with_distinction": True,
        "conduct": "wzorowe",
        "subjects": [
            {"raw_subject_name": "Język polski", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język angielski IV.1r.", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język francuski IV.1p.", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Filozofia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Fizyka", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Chemia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Biologia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Geografia", "raw_grade_value": "dobry"},
            {"raw_subject_name": "Informatyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Wychowanie fizyczne", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Edukacja dla bezpieczeństwa", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Biznes i zarządzanie", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia i teraźniejszość", "raw_grade_value": "celujący"},
        ],
        "advanced_subjects": [
            "Język angielski",
            "Geografia",
            "Matematyka",
            "Fizyka",
        ],
    }


# ─── extract_to_canonical ──────────────────────────────────────
def test_extract_to_canonical_minimal_smoke(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    t = extract_to_canonical(polish_profile, raw)
    assert t.source_profile_id == "pl.lo.swiadectwo_szkolne.v1"
    assert t.student.full_name == "Jan Kowalski"
    assert t.student.school_year == "2023/2024"
    assert t.student.source_year_index == 1
    assert t.student.target_year_index == 2
    assert t.student.promoted is True
    assert t.student.promoted_with_distinction is True
    assert len(t.subjects) == 15
    assert t.conduct is not None
    assert t.conduct.level is CanonicalConductLevel.EXEMPLARY
    assert t.religion_ethics is None  # excluded by default


def test_extract_to_canonical_marks_advanced_subjects(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    t = extract_to_canonical(polish_profile, raw)
    advanced_canon = {s.canonical_id for s in t.subjects if s.is_advanced}
    assert CanonicalSubjectId.L2_ENGLISH in advanced_canon  # "Język angielski IV.1r." → ENGLISH
    assert CanonicalSubjectId.GEOGRAPHY in advanced_canon
    assert CanonicalSubjectId.MATHEMATICS in advanced_canon
    assert CanonicalSubjectId.PHYSICS in advanced_canon
    # Non-advanced spot check
    assert not any(
        s.is_advanced for s in t.subjects if s.canonical_id is CanonicalSubjectId.L1_NATIVE
    )


def test_extract_to_canonical_resolves_grades(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    t = extract_to_canonical(polish_profile, raw)
    by_id = {s.canonical_id: s for s in t.subjects if s.canonical_id is not None}
    math = by_id[CanonicalSubjectId.MATHEMATICS]
    assert math.grade is not None
    assert math.grade.level_categorical is CanonicalGradeLevel.EXCELLENT
    assert math.grade.raw_source_value == "celujący"
    geog = by_id[CanonicalSubjectId.GEOGRAPHY]
    assert geog.grade is not None
    assert geog.grade.level_categorical is CanonicalGradeLevel.GOOD


def test_extract_to_canonical_unknown_class_raises(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    raw["current_class_name"] = "siódmej"  # not in PL year system
    with pytest.raises(MappingError):
        extract_to_canonical(polish_profile, raw)


def test_extract_to_canonical_unknown_grade_raises(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    raw["subjects"] = [
        {"raw_subject_name": "Matematyka", "raw_grade_value": "wonderful"},
    ]
    with pytest.raises(MappingError):
        extract_to_canonical(polish_profile, raw)


def test_extract_to_canonical_unknown_subject_yields_warning(polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    raw["subjects"].append(
        {"raw_subject_name": "Klub szachowy", "raw_grade_value": "celujący"},
    )
    t = extract_to_canonical(polish_profile, raw)
    assert any("klub szachowy" in w.lower() for w in t.extraction_warnings)


# ─── canonical_to_render_data ──────────────────────────────────
def test_render_data_for_grade9_template(polish_profile, us_hs_target) -> None:
    raw = _anonymized_polish_grade9_extraction()
    transcript = extract_to_canonical(polish_profile, raw)
    rd = canonical_to_render_data(us_hs_target, transcript)

    assert rd.template_key == "grade_9"
    # Spot-checks of key cells
    assert rd.cells["A2"] == "Jan Kowalski"
    # Conduct (wzorowe → "Exemplary" via target conduct scale's display value)
    assert rd.cells["D3"] == "wzorowe"
    # Mathematics → A+ (celujący)
    assert rd.cells["D19"] == "A+"
    # Mathematics with advanced flag = 108 + 27 = 135h
    assert rd.cells["E19"] == "135h"
    # Polish (L1_NATIVE) → A (bardzo dobry), not advanced → 108h
    assert rd.cells["D5"] == "A"
    assert rd.cells["E5"] == "108h"
    # English advanced → 81 + 27 = 108h
    assert rd.cells["D6"] == "A"
    assert rd.cells["E6"] == "108h"
    # Geography advanced → 54 + 27 = 81h
    assert rd.cells["D15"] == "B"  # dobry
    assert rd.cells["E15"] == "81h"
    # Physics advanced → 54 + 27 = 81h
    assert rd.cells["D18"] == "A"  # bardzo dobry
    assert rd.cells["E18"] == "81h"
    # Religion/Ethics excluded by default
    assert rd.cells.get("D4") is None
    # No critical warnings
    assert all("did not validate" not in w.lower() for w in rd.warnings)


def test_render_data_includes_all_subject_cells(us_hs_target, polish_profile) -> None:
    raw = _anonymized_polish_grade9_extraction()
    transcript = extract_to_canonical(polish_profile, raw)
    rd = canonical_to_render_data(us_hs_target, transcript)
    # Every binding's cell must be present in the output (even if value=None)
    template = us_hs_target.template_for_year(9)
    assert template is not None
    for binding in template.bindings:
        assert binding.cell in rd.cells

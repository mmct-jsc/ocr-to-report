"""Phase 2 — profile + target loader integration tests.

These read the *real* shipped bundles from `profiles/` and `targets/` and
verify they load + can drive the mapping engine.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ocr_to_report.core.enums.canonical import CanonicalSubjectId
from ocr_to_report.core.profiles import (
    ProfileLoadError,
    ProfileRegistry,
    load_profile_bundle,
)
from ocr_to_report.core.targets import (
    TargetLoadError,
    TargetRegistry,
    load_target_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
PROFILES_DIR = REPO_ROOT / "profiles"
TARGETS_DIR = REPO_ROOT / "targets"


# ─── Polish profile loads + structure ──────────────────────────
def test_polish_profile_loads() -> None:
    bundle = load_profile_bundle(PROFILES_DIR / "pl.lo.swiadectwo_szkolne.v1")
    assert bundle.id == "pl.lo.swiadectwo_szkolne.v1"
    assert bundle.manifest.source_language == "pl"
    assert bundle.manifest.education_system == "PL"
    assert "us-hs.v1" in bundle.manifest.default_target_systems


def test_polish_grade_scale_has_six_levels() -> None:
    bundle = load_profile_bundle(PROFILES_DIR / "pl.lo.swiadectwo_szkolne.v1")
    assert len(bundle.grade_scale.levels) == 6
    # spot-check the Polish 6-point scale
    assert bundle.grade_scale.lookup("celujący") is not None
    assert bundle.grade_scale.lookup("bardzo dobry") is not None
    assert bundle.grade_scale.lookup("dobry") is not None
    assert bundle.grade_scale.lookup("dostateczny") is not None
    assert bundle.grade_scale.lookup("dopuszczający") is not None
    assert bundle.grade_scale.lookup("niedostateczny") is not None
    # numeric aliases
    assert bundle.grade_scale.lookup("5") == bundle.grade_scale.lookup("bardzo dobry")
    assert bundle.grade_scale.lookup("6") == bundle.grade_scale.lookup("celujący")


def test_polish_year_system_four_years() -> None:
    bundle = load_profile_bundle(PROFILES_DIR / "pl.lo.swiadectwo_szkolne.v1")
    assert len(bundle.year_system.entries) == 4
    assert bundle.year_system.lookup("pierwszej") is bundle.year_system.entries[0]
    assert bundle.year_system.lookup("drugiej") is bundle.year_system.entries[1]


def test_polish_vocabulary_known_subjects() -> None:
    bundle = load_profile_bundle(PROFILES_DIR / "pl.lo.swiadectwo_szkolne.v1")
    cases = {
        "Matematyka": CanonicalSubjectId.MATHEMATICS,
        "Fizyka": CanonicalSubjectId.PHYSICS,
        "Język polski": CanonicalSubjectId.L1_NATIVE,
        "Język angielski": CanonicalSubjectId.L2_ENGLISH,
        "Język angielski IV.1r.": CanonicalSubjectId.L2_ENGLISH,  # alias
        "Historia": CanonicalSubjectId.HISTORY,
        "Historia i teraźniejszość": CanonicalSubjectId.HISTORY_AND_PRESENT,
        "Biznes i zarządzanie": CanonicalSubjectId.ENTREPRENEURSHIP,
    }
    for raw, expected in cases.items():
        m = bundle.vocabulary.lookup(raw)
        assert m is not None, f"missing vocabulary entry for {raw!r}"
        assert m.canonical_id == expected, f"{raw!r} → {m.canonical_id}, expected {expected}"


# ─── US-HS target loads + structure ────────────────────────────
def test_us_hs_target_loads() -> None:
    bundle = load_target_bundle(TARGETS_DIR / "us-hs.v1")
    assert bundle.id == "us-hs.v1"
    assert bundle.manifest.output_language == "en"
    assert "xlsx" in bundle.manifest.output_formats


def test_us_hs_grade_scale_full_coverage() -> None:
    bundle = load_target_bundle(TARGETS_DIR / "us-hs.v1")
    # Every canonical grade level must map to exactly one display value
    from ocr_to_report.core.enums.canonical import CanonicalGradeLevel  # noqa: PLC0415

    expected_displays = {
        CanonicalGradeLevel.EXCELLENT: "A+",
        CanonicalGradeLevel.VERY_GOOD: "A",
        CanonicalGradeLevel.GOOD: "B",
        CanonicalGradeLevel.SATISFACTORY: "C",
        CanonicalGradeLevel.PASS: "D-E",
        CanonicalGradeLevel.FAIL: "F",
    }
    for canonical, display in expected_displays.items():
        assert bundle.grade_scale.for_canonical(canonical).display_value == display


def test_us_hs_year_system_maps_polish_to_grades() -> None:
    bundle = load_target_bundle(TARGETS_DIR / "us-hs.v1")
    for src_idx, target_idx in [(1, 9), (2, 10), (3, 11), (4, 12)]:
        entry = bundle.year_system.for_source_year(src_idx)
        assert entry is not None
        assert entry.target_index == target_idx


def test_us_hs_grade9_template_present() -> None:
    bundle = load_target_bundle(TARGETS_DIR / "us-hs.v1")
    grade9 = bundle.template_for_year(9)
    assert grade9 is not None
    assert grade9.key == "grade_9"
    assert grade9.output_format == "xlsx"
    assert grade9.blob_path == "templates/grade_9.xlsx"
    # Template's xlsx file exists on disk
    assert (TARGETS_DIR / "us-hs.v1" / grade9.blob_path).is_file()
    # Has bindings for the major subjects
    bound_kinds = {(b.cell, b.kind, b.subject_id) for b in grade9.bindings}
    from ocr_to_report.core.target.templates import TemplateBindingKind  # noqa: PLC0415

    assert ("A2", TemplateBindingKind.STUDENT_FULL_NAME, None) in bound_kinds
    assert (
        "D19",
        TemplateBindingKind.SUBJECT_GRADE,
        CanonicalSubjectId.MATHEMATICS,
    ) in bound_kinds


def test_us_hs_taxonomy_includes_polish_curriculum_subjects() -> None:
    bundle = load_target_bundle(TARGETS_DIR / "us-hs.v1")
    must_have = {
        CanonicalSubjectId.L1_NATIVE,
        CanonicalSubjectId.MATHEMATICS,
        CanonicalSubjectId.PHYSICS,
        CanonicalSubjectId.HISTORY,
        CanonicalSubjectId.HISTORY_AND_PRESENT,
        CanonicalSubjectId.PHYSICAL_EDUCATION,
        CanonicalSubjectId.SAFETY_EDUCATION,
        CanonicalSubjectId.ENTREPRENEURSHIP,
    }
    actual = {e.canonical_id for e in bundle.subject_taxonomy.entries}
    assert must_have <= actual


# ─── Registries ────────────────────────────────────────────────
def test_profile_registry_discovers_polish() -> None:
    pr = ProfileRegistry(PROFILES_DIR)
    assert "pl.lo.swiadectwo_szkolne.v1" in pr.ids()
    assert pr.has("pl.lo.swiadectwo_szkolne.v1")


def test_target_registry_discovers_us_hs() -> None:
    tr = TargetRegistry(TARGETS_DIR)
    assert "us-hs.v1" in tr.ids()
    assert tr.has("us-hs.v1")


def test_profile_registry_lazy_load_caches() -> None:
    pr = ProfileRegistry(PROFILES_DIR)
    a = pr.get("pl.lo.swiadectwo_szkolne.v1")
    b = pr.get("pl.lo.swiadectwo_szkolne.v1")
    assert a is b  # cached


def test_unknown_profile_id_raises() -> None:
    pr = ProfileRegistry(PROFILES_DIR)
    from ocr_to_report.core.errors.domain import ProfileNotFoundError  # noqa: PLC0415

    with pytest.raises(ProfileNotFoundError):
        pr.get("does.not.exist.v1")


# ─── Loader negative cases ─────────────────────────────────────
def test_missing_bundle_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(ProfileLoadError):
        load_profile_bundle(tmp_path / "nonexistent")


def test_target_missing_bundle_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(TargetLoadError):
        load_target_bundle(tmp_path / "nonexistent")

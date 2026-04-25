"""Target system schema tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.enums.canonical import (
    CanonicalGradeLevel,
    CanonicalSubjectId,
)
from ocr_to_report.core.target.bundle import TargetBundle
from ocr_to_report.core.target.grade_scale import (
    TargetGradeScale,
    TargetGradeScaleLevel,
)
from ocr_to_report.core.target.manifest import TargetManifest
from ocr_to_report.core.target.subject_taxonomy import (
    TargetSubjectEntry,
    TargetSubjectTaxonomy,
)
from ocr_to_report.core.target.templates import (
    TargetTemplate,
    TemplateBindingKind,
    TemplateCellBinding,
)
from ocr_to_report.core.target.year_system import TargetYearEntry, TargetYearSystem


# ─── TargetGradeScale ──────────────────────────────────────────
def _us_grade_scale() -> TargetGradeScale:
    return TargetGradeScale(
        id="us.letter.v1",
        levels=[
            TargetGradeScaleLevel(
                display_value="A+",
                canonical_levels=[CanonicalGradeLevel.EXCELLENT],
                label="Excellent",
            ),
            TargetGradeScaleLevel(
                display_value="A",
                canonical_levels=[CanonicalGradeLevel.VERY_GOOD],
                label="Very Good",
            ),
            TargetGradeScaleLevel(
                display_value="B",
                canonical_levels=[CanonicalGradeLevel.GOOD],
                label="Good",
            ),
            TargetGradeScaleLevel(
                display_value="C",
                canonical_levels=[CanonicalGradeLevel.SATISFACTORY],
                label="Satisfactory",
            ),
            TargetGradeScaleLevel(
                display_value="D-E",
                canonical_levels=[CanonicalGradeLevel.PASS],
                label="Pass",
            ),
            TargetGradeScaleLevel(
                display_value="F",
                canonical_levels=[CanonicalGradeLevel.FAIL],
                label="Fail",
            ),
        ],
    )


def test_target_grade_scale_for_canonical() -> None:
    s = _us_grade_scale()
    assert s.for_canonical(CanonicalGradeLevel.EXCELLENT).display_value == "A+"
    assert s.for_canonical(CanonicalGradeLevel.PASS).display_value == "D-E"


def test_target_grade_scale_rejects_overlap() -> None:
    with pytest.raises(ValueError):
        TargetGradeScale(
            id="x.v1",
            levels=[
                TargetGradeScaleLevel(
                    display_value="A",
                    canonical_levels=[CanonicalGradeLevel.EXCELLENT, CanonicalGradeLevel.VERY_GOOD],
                    label="A",
                ),
                TargetGradeScaleLevel(
                    display_value="B",
                    canonical_levels=[CanonicalGradeLevel.VERY_GOOD],  # duplicates the above
                    label="B",
                ),
            ],
        )


def test_target_grade_scale_rejects_unmapped() -> None:
    with pytest.raises(ValueError):
        TargetGradeScale(
            id="x.v1",
            levels=[
                TargetGradeScaleLevel(
                    display_value="HI",
                    canonical_levels=[CanonicalGradeLevel.EXCELLENT],
                    label="hi",
                ),
                TargetGradeScaleLevel(
                    display_value="LO",
                    canonical_levels=[CanonicalGradeLevel.FAIL],
                    label="lo",
                ),
                # missing PASS, SATISFACTORY, GOOD, VERY_GOOD
            ],
        )


# ─── TargetYearSystem ──────────────────────────────────────────
def test_year_system_unique_indices() -> None:
    with pytest.raises(ValueError):
        TargetYearSystem(
            id="us-hs.year.v1",
            entries=[
                TargetYearEntry(target_index=9, source_year_index=1, display_name="9"),
                TargetYearEntry(target_index=9, source_year_index=2, display_name="9"),  # dup
            ],
        )


def test_year_system_unique_source_indices() -> None:
    with pytest.raises(ValueError):
        TargetYearSystem(
            id="us-hs.year.v1",
            entries=[
                TargetYearEntry(target_index=9, source_year_index=1, display_name="9"),
                TargetYearEntry(target_index=10, source_year_index=1, display_name="10"),  # dup
            ],
        )


def test_year_system_lookup() -> None:
    sys = TargetYearSystem(
        id="us-hs.year.v1",
        entries=[
            TargetYearEntry(target_index=9, source_year_index=1, display_name="Grade 9"),
            TargetYearEntry(target_index=10, source_year_index=2, display_name="Grade 10"),
        ],
    )
    assert sys.for_source_year(1) and sys.for_source_year(1).target_index == 9  # type: ignore[union-attr]
    assert sys.for_source_year(99) is None


# ─── TargetSubjectTaxonomy ─────────────────────────────────────
def test_subject_taxonomy_requires_hours_or_optional() -> None:
    with pytest.raises(ValueError):
        TargetSubjectTaxonomy(
            id="us-hs.subjects.v1",
            entries=[
                TargetSubjectEntry(
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                    display_name="Mathematics",
                    # neither base_hours_default nor base_hours_per_year
                    # AND not optional → invalid
                ),
            ],
        )


def test_subject_taxonomy_optional_subject_no_hours_ok() -> None:
    t = TargetSubjectTaxonomy(
        id="us-hs.subjects.v1",
        entries=[
            TargetSubjectEntry(
                canonical_id=CanonicalSubjectId.ART,
                display_name="Art",
                optional=True,
            ),
        ],
    )
    assert t.entries[0].hours_for_year(1) is None


def test_subject_taxonomy_per_year_hours_override() -> None:
    e = TargetSubjectEntry(
        canonical_id=CanonicalSubjectId.MATHEMATICS,
        display_name="Mathematics",
        base_hours_default=108,
        base_hours_per_year={11: 81, 12: 81},
    )
    assert e.hours_for_year(9) == 108
    assert e.hours_for_year(11) == 81
    assert e.hours_for_year(12) == 81


def test_subject_taxonomy_unique_canonical_ids() -> None:
    with pytest.raises(ValueError):
        TargetSubjectTaxonomy(
            id="x.v1",
            entries=[
                TargetSubjectEntry(
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                    display_name="A",
                    base_hours_default=10,
                ),
                TargetSubjectEntry(
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                    display_name="B",
                    base_hours_default=10,
                ),
            ],
        )


# ─── TemplateCellBinding ───────────────────────────────────────
def test_subject_grade_binding_requires_subject_id() -> None:
    with pytest.raises(ValueError):
        TemplateCellBinding(
            cell="D5",
            kind=TemplateBindingKind.SUBJECT_GRADE,
            # subject_id missing
        )


def test_non_subject_binding_must_not_set_subject_id() -> None:
    with pytest.raises(ValueError):
        TemplateCellBinding(
            cell="A1",
            kind=TemplateBindingKind.STUDENT_FULL_NAME,
            subject_id=CanonicalSubjectId.MATHEMATICS,
        )


def test_literal_binding_requires_value() -> None:
    with pytest.raises(ValueError):
        TemplateCellBinding(
            cell="B2",
            kind=TemplateBindingKind.LITERAL,
        )


def test_literal_binding_with_value_ok() -> None:
    b = TemplateCellBinding(
        cell="B2",
        kind=TemplateBindingKind.LITERAL,
        literal_value="Header text",
    )
    assert b.literal_value == "Header text"


def test_subject_grade_binding_with_subject_id_ok() -> None:
    b = TemplateCellBinding(
        cell="D5",
        kind=TemplateBindingKind.SUBJECT_GRADE,
        subject_id=CanonicalSubjectId.MATHEMATICS,
    )
    assert b.subject_id is CanonicalSubjectId.MATHEMATICS


@pytest.mark.parametrize("bad_cell", ["a1", "1A", "AA", "A", "AAAA1", "A12345678"])
def test_invalid_cell_pattern(bad_cell: str) -> None:
    with pytest.raises(ValueError):
        TemplateCellBinding(
            cell=bad_cell,
            kind=TemplateBindingKind.STUDENT_FULL_NAME,
        )


# ─── TargetTemplate ────────────────────────────────────────────
def test_template_unique_cells() -> None:
    with pytest.raises(ValueError):
        TargetTemplate(
            key="grade_9",
            blob_path="templates/grade_9.xlsx",
            output_format="xlsx",
            target_year_index=9,
            bindings=[
                TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_FULL_NAME),
                TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_SCHOOL_NAME),
            ],
        )


# ─── TargetBundle ──────────────────────────────────────────────
def _us_hs_bundle() -> TargetBundle:
    return TargetBundle(
        manifest=TargetManifest(
            id="us-hs.v1",
            name="US High School",
            version="1.0",
            output_language="en",
            education_system="US",
        ),
        grade_scale=_us_grade_scale(),
        year_system=TargetYearSystem(
            id="us-hs.year.v1",
            entries=[
                TargetYearEntry(target_index=9, source_year_index=1, display_name="Grade 9"),
                TargetYearEntry(target_index=10, source_year_index=2, display_name="Grade 10"),
            ],
        ),
        subject_taxonomy=TargetSubjectTaxonomy(
            id="us-hs.subjects.v1",
            entries=[
                TargetSubjectEntry(
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                    display_name="Mathematics",
                    base_hours_default=108,
                ),
            ],
        ),
        conduct_scale=_us_grade_scale(),  # reusing for shape only
        templates=[
            TargetTemplate(
                key="grade_9",
                blob_path="templates/grade_9.xlsx",
                output_format="xlsx",
                target_year_index=9,
                bindings=[
                    TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_FULL_NAME),
                ],
            ),
        ],
    )


def test_target_bundle_constructs() -> None:
    b = _us_hs_bundle()
    assert b.id == "us-hs.v1"
    assert b.template_for_year(9).key == "grade_9"  # type: ignore[union-attr]


def test_target_bundle_template_format_must_match_manifest() -> None:
    with pytest.raises(ValueError):
        TargetBundle(
            manifest=TargetManifest(
                id="us-hs.v1",
                name="x",
                version="1.0",
                output_language="en",
                education_system="US",
                output_formats=["xlsx"],
            ),
            grade_scale=_us_grade_scale(),
            year_system=TargetYearSystem(
                id="x.v1",
                entries=[TargetYearEntry(target_index=9, source_year_index=1, display_name="9")],
            ),
            subject_taxonomy=TargetSubjectTaxonomy(
                id="x.v1",
                entries=[
                    TargetSubjectEntry(
                        canonical_id=CanonicalSubjectId.MATHEMATICS,
                        display_name="Math",
                        base_hours_default=10,
                    ),
                ],
            ),
            conduct_scale=_us_grade_scale(),
            templates=[
                TargetTemplate(
                    key="grade_9",
                    blob_path="templates/grade_9.csv",
                    output_format="csv",  # not in manifest.output_formats
                    target_year_index=9,
                    bindings=[
                        TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_FULL_NAME),
                    ],
                ),
            ],
        )


def test_target_bundle_unique_template_keys() -> None:
    with pytest.raises(ValueError):
        TargetBundle(
            manifest=TargetManifest(
                id="us-hs.v1",
                name="x",
                version="1.0",
                output_language="en",
                education_system="US",
            ),
            grade_scale=_us_grade_scale(),
            year_system=TargetYearSystem(
                id="x.v1",
                entries=[TargetYearEntry(target_index=9, source_year_index=1, display_name="9")],
            ),
            subject_taxonomy=TargetSubjectTaxonomy(
                id="x.v1",
                entries=[
                    TargetSubjectEntry(
                        canonical_id=CanonicalSubjectId.MATHEMATICS,
                        display_name="Math",
                        base_hours_default=10,
                    ),
                ],
            ),
            conduct_scale=_us_grade_scale(),
            templates=[
                TargetTemplate(
                    key="grade_9",
                    blob_path="t1.xlsx",
                    output_format="xlsx",
                    bindings=[
                        TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_FULL_NAME),
                    ],
                ),
                TargetTemplate(
                    key="grade_9",
                    blob_path="t2.xlsx",
                    output_format="xlsx",
                    bindings=[
                        TemplateCellBinding(cell="A1", kind=TemplateBindingKind.STUDENT_FULL_NAME),
                    ],
                ),
            ],
        )

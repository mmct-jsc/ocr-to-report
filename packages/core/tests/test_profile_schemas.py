"""Source profile schema tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.enums.canonical import CanonicalSubjectId
from ocr_to_report.core.profile.bundle import ProfileBundle
from ocr_to_report.core.profile.extraction_schema import (
    ExtractionField,
    ExtractionFieldKind,
    ProfileExtractionSchema,
)
from ocr_to_report.core.profile.grade_scale import GradeScaleLevel, ProfileGradeScale
from ocr_to_report.core.profile.manifest import (
    ProfileFingerprint,
    ProfileManifest,
)
from ocr_to_report.core.profile.vocabulary import ProfileVocabulary, SubjectMapping
from ocr_to_report.core.profile.year_system import ProfileYearSystem, YearSystemEntry


# ─── ProfileFingerprint ────────────────────────────────────────
def test_fingerprint_pages_consistent() -> None:
    with pytest.raises(ValueError):
        ProfileFingerprint(min_pages=5, max_pages=2)


def test_fingerprint_default_pages() -> None:
    fp = ProfileFingerprint()
    assert fp.min_pages == 1
    assert fp.max_pages == 2


# ─── ProfileManifest ───────────────────────────────────────────
def test_manifest_minimal_valid() -> None:
    m = ProfileManifest(
        id="pl.lo.swiadectwo_szkolne.v1",
        name="Polish Liceum School Certificate",
        version="1.0",
        source_language="pl",
        education_system="PL",
        document_type="school_certificate",
        fingerprint=ProfileFingerprint(),
    )
    assert m.id == "pl.lo.swiadectwo_szkolne.v1"


@pytest.mark.parametrize(
    "bad_id",
    [
        "pl.lo.swiadectwo_szkolne",  # missing .vN suffix
        "PL.LO.swiadectwo.v1",  # uppercase
        "pl.lo.v1.suffix",  # extra after .vN
        "pl/lo/v1",  # slashes
        "1.lo.x.v1",  # starts with digit
    ],
)
def test_manifest_invalid_id(bad_id: str) -> None:
    with pytest.raises(ValueError):
        ProfileManifest(
            id=bad_id,
            name="x",
            version="1.0",
            source_language="pl",
            education_system="PL",
            document_type="school_certificate",
            fingerprint=ProfileFingerprint(),
        )


# Note: format validator only — invalid ISO-639-1 codes that happen to
# match the "two lowercase letters" pattern (e.g., 'zz') pass at this layer.
# Profile loader (Phase 2) will validate against the actual ISO-639-1 set.
@pytest.mark.parametrize("bad_lang", ["PL", "polish", "p", "pol", "p1", "1p", " pl"])
def test_manifest_invalid_language(bad_lang: str) -> None:
    with pytest.raises(ValueError):
        ProfileManifest(
            id="pl.lo.swiadectwo_szkolne.v1",
            name="x",
            version="1.0",
            source_language=bad_lang,
            education_system="PL",
            document_type="school_certificate",
            fingerprint=ProfileFingerprint(),
        )


# ─── GradeScaleLevel + ProfileGradeScale ───────────────────────
def _polish_scale() -> ProfileGradeScale:
    return ProfileGradeScale(
        id="pl.6point.v1",
        levels=[
            GradeScaleLevel(
                raw_value="niedostateczny",
                aliases=["1"],
                normalized=0.0,
                label="Fail",
                is_passing=False,
            ),
            GradeScaleLevel(
                raw_value="dopuszczający",
                aliases=["2"],
                normalized=1 / 6,
                label="Pass",
                is_passing=True,
            ),
            GradeScaleLevel(
                raw_value="dostateczny",
                aliases=["3"],
                normalized=2 / 6,
                label="Satisfactory",
                is_passing=True,
            ),
            GradeScaleLevel(
                raw_value="dobry", aliases=["4"], normalized=3 / 6, label="Good", is_passing=True
            ),
            GradeScaleLevel(
                raw_value="bardzo dobry",
                aliases=["5", "bdb"],
                normalized=4 / 6,
                label="Very Good",
                is_passing=True,
            ),
            GradeScaleLevel(
                raw_value="celujący",
                aliases=["6"],
                normalized=5 / 6,
                label="Excellent",
                is_passing=True,
            ),
        ],
    )


def test_grade_scale_lookup_via_alias() -> None:
    scale = _polish_scale()
    assert scale.lookup("5") is scale.levels[4]
    assert scale.lookup("BDB") is scale.levels[4]
    assert scale.lookup("Bardzo Dobry") is scale.levels[4]
    assert scale.lookup("nope") is None


def test_grade_scale_must_be_sorted_ascending() -> None:
    with pytest.raises(ValueError):
        ProfileGradeScale(
            id="x.v1",
            levels=[
                GradeScaleLevel(raw_value="hi", normalized=0.9, label="hi", is_passing=True),
                GradeScaleLevel(raw_value="lo", normalized=0.1, label="lo", is_passing=False),
            ],
        )


def test_grade_scale_requires_passing_and_failing() -> None:
    with pytest.raises(ValueError):
        ProfileGradeScale(
            id="x.v1",
            levels=[
                GradeScaleLevel(raw_value="ok", normalized=0.5, label="ok", is_passing=True),
                GradeScaleLevel(raw_value="great", normalized=0.9, label="great", is_passing=True),
            ],
        )


def test_grade_scale_aliases_unique_globally() -> None:
    with pytest.raises(ValueError):
        ProfileGradeScale(
            id="x.v1",
            levels=[
                GradeScaleLevel(
                    raw_value="lo", aliases=["dup"], normalized=0.0, label="lo", is_passing=False
                ),
                GradeScaleLevel(
                    raw_value="hi", aliases=["dup"], normalized=0.9, label="hi", is_passing=True
                ),
            ],
        )


# ─── YearSystem ────────────────────────────────────────────────
def test_year_system_contiguous_indices() -> None:
    with pytest.raises(ValueError):
        ProfileYearSystem(
            id="pl.lo.4year.v1",
            entries=[
                YearSystemEntry(index=1, raw_name="pierwszej", label="1"),
                YearSystemEntry(index=3, raw_name="trzeciej", label="3"),
            ],
        )


def test_year_system_lookup_case_insensitive() -> None:
    sys = ProfileYearSystem(
        id="pl.lo.4year.v1",
        entries=[
            YearSystemEntry(index=1, raw_name="pierwszej", aliases=["1st"], label="1"),
            YearSystemEntry(index=2, raw_name="drugiej", aliases=["2nd"], label="2"),
        ],
    )
    assert sys.lookup("PIERWSZEJ") is sys.entries[0]
    assert sys.lookup("2nd") is sys.entries[1]
    assert sys.lookup("nope") is None


# ─── Vocabulary ────────────────────────────────────────────────
def test_vocabulary_lookup_handles_aliases() -> None:
    v = ProfileVocabulary(
        id="pl.subjects.v1",
        mappings=[
            SubjectMapping(
                raw_name="Matematyka",
                aliases=["Math", "Mat"],
                canonical_id=CanonicalSubjectId.MATHEMATICS,
            ),
        ],
    )
    assert v.lookup("matematyka") is v.mappings[0]
    assert v.lookup("MAT") is v.mappings[0]
    assert v.lookup("Inna") is None


def test_vocabulary_rejects_duplicate_alias() -> None:
    with pytest.raises(ValueError):
        ProfileVocabulary(
            id="pl.subjects.v1",
            mappings=[
                SubjectMapping(
                    raw_name="A",
                    aliases=["dup"],
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                ),
                SubjectMapping(
                    raw_name="B",
                    aliases=["dup"],
                    canonical_id=CanonicalSubjectId.PHYSICS,
                ),
            ],
        )


# ─── ExtractionSchema ──────────────────────────────────────────
def _extraction_schema() -> ProfileExtractionSchema:
    return ProfileExtractionSchema(
        id="pl.extraction.v1",
        fields=[
            ExtractionField(
                name="full_name",
                description="Student full name as printed.",
                kind=ExtractionFieldKind.STRING,
            ),
            ExtractionField(
                name="subjects",
                description="Subject + grade rows.",
                kind=ExtractionFieldKind.SUBJECT_TABLE,
            ),
        ],
    )


def test_extraction_schema_requires_subject_table() -> None:
    with pytest.raises(ValueError):
        ProfileExtractionSchema(
            id="x.v1",
            fields=[
                ExtractionField(name="a", description="a", kind=ExtractionFieldKind.STRING),
                ExtractionField(name="b", description="b", kind=ExtractionFieldKind.INTEGER),
            ],
        )


def test_extraction_schema_unique_field_names() -> None:
    with pytest.raises(ValueError):
        ProfileExtractionSchema(
            id="x.v1",
            fields=[
                ExtractionField(name="a", description="a", kind=ExtractionFieldKind.STRING),
                ExtractionField(
                    name="a", description="dup", kind=ExtractionFieldKind.SUBJECT_TABLE
                ),
            ],
        )


# ─── ProfileBundle ─────────────────────────────────────────────
def test_profile_bundle_with_real_polish_inputs() -> None:
    bundle = ProfileBundle(
        manifest=ProfileManifest(
            id="pl.lo.swiadectwo_szkolne.v1",
            name="Polish Liceum School Certificate",
            version="1.0",
            source_language="pl",
            education_system="PL",
            document_type="school_certificate",
            fingerprint=ProfileFingerprint(
                header_patterns=[r"ŚWIADECTWO\s+SZKOLNE"],
                required_keywords=["szkoln"],
                min_pages=1,
                max_pages=2,
            ),
        ),
        extraction_schema=_extraction_schema(),
        vocabulary=ProfileVocabulary(
            id="pl.subjects.v1",
            mappings=[
                SubjectMapping(
                    raw_name="Matematyka",
                    canonical_id=CanonicalSubjectId.MATHEMATICS,
                ),
            ],
        ),
        grade_scale=_polish_scale(),
        conduct_scale=ProfileGradeScale(
            id="pl.conduct.v1",
            levels=[
                GradeScaleLevel(
                    raw_value="naganne", normalized=0.0, label="poor", is_passing=False
                ),
                GradeScaleLevel(
                    raw_value="wzorowe", normalized=1.0, label="exemplary", is_passing=True
                ),
            ],
        ),
        year_system=ProfileYearSystem(
            id="pl.lo.4year.v1",
            entries=[
                YearSystemEntry(index=1, raw_name="pierwszej", label="1st"),
                YearSystemEntry(index=2, raw_name="drugiej", label="2nd"),
                YearSystemEntry(index=3, raw_name="trzeciej", label="3rd"),
                YearSystemEntry(index=4, raw_name="czwartej", label="4th"),
            ],
        ),
        extraction_prompt_template="Extract from this transcript.\n{schema_json}",
    )
    assert bundle.id == "pl.lo.swiadectwo_szkolne.v1"


def test_profile_bundle_requires_template_slot() -> None:
    with pytest.raises(ValueError):
        ProfileBundle(
            manifest=ProfileManifest(
                id="pl.lo.swiadectwo_szkolne.v1",
                name="x",
                version="1.0",
                source_language="pl",
                education_system="PL",
                document_type="school_certificate",
                fingerprint=ProfileFingerprint(),
            ),
            extraction_schema=_extraction_schema(),
            vocabulary=ProfileVocabulary(
                id="x.v1",
                mappings=[
                    SubjectMapping(raw_name="X", canonical_id=CanonicalSubjectId.MATHEMATICS)
                ],
            ),
            grade_scale=_polish_scale(),
            conduct_scale=_polish_scale(),
            year_system=ProfileYearSystem(
                id="x.v1",
                entries=[YearSystemEntry(index=1, raw_name="a", label="a")],
            ),
            extraction_prompt_template="No interpolation slots here.",
        )

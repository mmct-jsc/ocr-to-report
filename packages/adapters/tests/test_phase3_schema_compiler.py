"""Profile-schema → JSON-schema compiler tests."""

from __future__ import annotations

from ocr_to_report.adapters.vision import compile_schema
from ocr_to_report.core.profile.extraction_schema import (
    ExtractionField,
    ExtractionFieldKind,
    ProfileExtractionSchema,
)


def _required(name: str, kind: ExtractionFieldKind, **kw: object) -> ExtractionField:
    return ExtractionField(
        name=name,
        description=f"Field {name}",
        kind=kind,
        required=True,
        **kw,  # type: ignore[arg-type]
    )


def test_compile_object_schema() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required("full_name", ExtractionFieldKind.STRING),
            _required("birth_date", ExtractionFieldKind.DATE),
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
        ],
    )
    compiled = compile_schema(profile_schema)
    assert compiled["type"] == "object"
    assert compiled["additionalProperties"] is False
    assert "full_name" in compiled["properties"]
    assert "birth_date" in compiled["properties"]
    assert "subjects" in compiled["properties"]
    assert set(compiled["required"]) == {"full_name", "birth_date", "subjects"}


def test_string_field_includes_pattern() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required(
                "school_year", ExtractionFieldKind.STRING, validation_pattern=r"^\d{4}/\d{4}$"
            ),
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
        ],
    )
    compiled = compile_schema(profile_schema)
    assert compiled["properties"]["school_year"]["pattern"] == r"^\d{4}/\d{4}$"


def test_date_field_format() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required("birth_date", ExtractionFieldKind.DATE),
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
        ],
    )
    compiled = compile_schema(profile_schema)
    assert compiled["properties"]["birth_date"]["format"] == "date"


def test_optional_fields_allow_null() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            ExtractionField(
                name="city",
                description="city",
                kind=ExtractionFieldKind.STRING,
                required=False,
            ),
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
        ],
    )
    compiled = compile_schema(profile_schema)
    assert compiled["properties"]["city"]["type"] == ["string", "null"]
    assert "city" not in compiled["required"]


def test_subject_table_shape() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
            _required("full_name", ExtractionFieldKind.STRING),
        ],
    )
    compiled = compile_schema(profile_schema)
    items = compiled["properties"]["subjects"]["items"]
    assert items["type"] == "object"
    assert "raw_subject_name" in items["properties"]
    assert "raw_grade_value" in items["properties"]
    assert items["required"] == ["raw_subject_name"]


def test_advanced_subjects_shape() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
            _required("advanced_subjects", ExtractionFieldKind.ADVANCED_SUBJECTS),
        ],
    )
    compiled = compile_schema(profile_schema)
    arr = compiled["properties"]["advanced_subjects"]
    assert arr["type"] == "array"
    assert arr["items"] == {"type": "string"}


def test_examples_carried_through() -> None:
    profile_schema = ProfileExtractionSchema(
        id="x.v1",
        fields=[
            _required("school_year", ExtractionFieldKind.STRING, examples=["2023/2024"]),
            _required("subjects", ExtractionFieldKind.SUBJECT_TABLE),
        ],
    )
    compiled = compile_schema(profile_schema)
    assert compiled["properties"]["school_year"]["examples"] == ["2023/2024"]

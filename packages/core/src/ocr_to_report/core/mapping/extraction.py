"""Raw extraction → :class:`CanonicalTranscript`.

The profile's extraction schema declares fields under conventional names so
the mapping engine can interpret them uniformly. The contract is captured
in :data:`CANONICAL_EXTRACTION_FIELDS`. Profile authors must use these
field names; the loader doesn't enforce that — but the mapping engine
will surface a clear error if a required field is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ocr_to_report.core.canonical.conduct import CanonicalConduct
from ocr_to_report.core.canonical.grade import CanonicalGrade
from ocr_to_report.core.canonical.student import CanonicalStudent
from ocr_to_report.core.canonical.subject import CanonicalSubject
from ocr_to_report.core.canonical.transcript import CanonicalTranscript
from ocr_to_report.core.enums.canonical import CanonicalConductLevel, CanonicalGradeLevel
from ocr_to_report.core.errors.domain import MappingError
from ocr_to_report.core.profile.bundle import ProfileBundle
from ocr_to_report.core.profile.grade_scale import (
    GradeScaleLevel,
    ProfileGradeScale,
)


# Conventional field names — profile extraction schemas MUST use these
# (additional fields are allowed and ignored by the mapping engine).
@dataclass(frozen=True, slots=True)
class _CanonicalFields:
    full_name: str = "full_name"
    birth_date: str = "birth_date"
    school_year: str = "school_year"
    current_class_name: str = "current_class_name"
    promoted: str = "promoted"
    promoted_with_distinction: str = "promoted_with_distinction"
    school_name: str = "school_name"
    city: str = "city"
    region: str = "region"
    subjects: str = "subjects"
    advanced_subjects: str = "advanced_subjects"
    conduct: str = "conduct"
    religion_ethics: str = "religion_ethics"


CANONICAL_EXTRACTION_FIELDS = _CanonicalFields()


def extract_to_canonical(
    profile: ProfileBundle,
    raw: dict[str, Any],
    *,
    extraction_confidence: float = 1.0,
    include_religion_ethics: bool = False,
) -> CanonicalTranscript:
    """Translate a raw extraction dict into a :class:`CanonicalTranscript`.

    Args:
        profile: The source profile bundle that produced the raw extraction.
        raw: The dict returned by the vision adapter. Field names must
            match the profile's extraction schema.
        extraction_confidence: Per-call extraction confidence to apply when
            the raw extraction does not carry per-field confidence values.
        include_religion_ethics: If True, the religion/ethics field is
            included (GDPR Art. 9 — see core/pii/classes.py for handling
            rules). Default: excluded.

    Raises :class:`MappingError` on any inconsistency the canonical model
    would otherwise reject (unknown grade word, unknown class, missing
    required field, etc.).
    """
    f = CANONICAL_EXTRACTION_FIELDS
    student = _build_student(profile, raw, f, extraction_confidence)
    subjects = _build_subjects(profile, raw, f, extraction_confidence)
    conduct = _build_conduct(profile, raw, f, extraction_confidence)

    religion_ethics: CanonicalGrade | None = None
    if include_religion_ethics:
        religion_ethics = _build_religion_ethics(profile, raw, f, extraction_confidence)

    advanced_raw = list(raw.get(f.advanced_subjects, []) or [])

    floors = [student.confidence, *(s.confidence for s in subjects)]
    if conduct is not None:
        floors.append(conduct.confidence)
    if religion_ethics is not None:
        floors.append(religion_ethics.confidence)
    overall = min(floors) if floors else extraction_confidence

    warnings: list[str] = [
        f"unrecognized subject: {s.raw_source_name!r}" for s in subjects if s.canonical_id is None
    ]

    try:
        return CanonicalTranscript(
            source_profile_id=profile.id,
            student=student,
            subjects=subjects,
            conduct=conduct,
            religion_ethics=religion_ethics,
            advanced_raw_names=advanced_raw,
            overall_confidence=overall,
            extraction_warnings=warnings,
        )
    except ValueError as e:
        raise MappingError(
            f"canonical transcript validation failed: {e}",
            profile_id=profile.id,
        ) from e


# ─── Student ──────────────────────────────────────────────────
def _build_student(
    profile: ProfileBundle,
    raw: dict[str, Any],
    f: _CanonicalFields,
    confidence: float,
) -> CanonicalStudent:
    full_name = _required_str(raw, f.full_name)
    school_name = _required_str(raw, f.school_name)
    school_year = _required_str(raw, f.school_year)
    current_class_name = _required_str(raw, f.current_class_name)

    year_entry = profile.year_system.lookup(current_class_name)
    if year_entry is None:
        raise MappingError(
            f"current_class_name {current_class_name!r} not in year system "
            f"{profile.year_system.id!r}",
            current_class_name=current_class_name,
            year_system_id=profile.year_system.id,
        )
    source_year_index = year_entry.index

    promoted = bool(raw.get(f.promoted, profile.year_system.promotes_to_next_year))
    target_year_index = source_year_index + (1 if promoted else 0)

    birth_date_raw = raw.get(f.birth_date)
    birth_date_value = _parse_date(birth_date_raw, f.birth_date) if birth_date_raw else None

    try:
        return CanonicalStudent(
            full_name=full_name,
            birth_date=birth_date_value,
            school_year=school_year,
            source_year_index=source_year_index,
            target_year_index=target_year_index,
            promoted=promoted,
            promoted_with_distinction=bool(raw.get(f.promoted_with_distinction, False)),
            school_name=school_name,
            city=raw.get(f.city) or None,
            region=raw.get(f.region) or None,
            confidence=confidence,
        )
    except ValueError as e:
        raise MappingError(f"student record validation failed: {e}") from e


# ─── Subjects ─────────────────────────────────────────────────
def _build_subjects(
    profile: ProfileBundle,
    raw: dict[str, Any],
    f: _CanonicalFields,
    confidence: float,
) -> list[CanonicalSubject]:
    rows = raw.get(f.subjects, []) or []
    if not isinstance(rows, list):
        raise MappingError(f"{f.subjects!r} must be a list")

    advanced_set = _normalize_advanced(raw.get(f.advanced_subjects, []) or [])

    subjects: list[CanonicalSubject] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise MappingError(f"subject row #{i} must be a dict")

        raw_name = _required_str(row, "raw_subject_name", context=f"subject row #{i}")
        mapping = profile.vocabulary.lookup(raw_name)

        grade_value = row.get("raw_grade_value")
        grade: CanonicalGrade | None = None
        if grade_value:
            grade = _resolve_grade(profile.grade_scale, str(grade_value), confidence)

        # The "advanced" listing on page 1 typically uses the canonical
        # subject name (e.g., "Język angielski"), not the variant on the
        # grade row (e.g., "Język angielski IV.1r."). Match against the
        # row's raw name AND the vocabulary entry's canonical name and
        # aliases so either form on either side is recognized.
        candidates: list[str] = [raw_name]
        if mapping is not None:
            candidates.append(mapping.raw_name)
            candidates.extend(mapping.aliases)
        is_advanced = any(c.casefold().strip() in advanced_set for c in candidates)

        try:
            subjects.append(
                CanonicalSubject(
                    canonical_id=mapping.canonical_id if mapping else None,
                    raw_source_name=raw_name,
                    grade=grade,
                    base_hours=row.get("base_hours"),
                    is_advanced=is_advanced,
                    confidence=row.get("confidence", confidence),
                    notes=row.get("notes") or None,
                )
            )
        except ValueError as e:
            raise MappingError(f"subject row #{i} validation failed: {e}") from e
    return subjects


def _normalize_advanced(advanced: list[Any]) -> set[str]:
    return {str(s).casefold().strip() for s in advanced if s}


def _resolve_grade(scale: ProfileGradeScale, raw_value: str, confidence: float) -> CanonicalGrade:
    level: GradeScaleLevel | None = scale.lookup(raw_value)
    if level is None:
        raise MappingError(
            f"unknown grade {raw_value!r} in scale {scale.id!r}",
            raw_value=raw_value,
            scale_id=scale.id,
        )
    try:
        return CanonicalGrade.from_normalized(
            level.normalized,
            raw_source_value=level.raw_value,
            raw_source_scale_id=scale.id,
            confidence=min(confidence, level.confidence),
        )
    except ValueError as e:
        raise MappingError(f"could not build canonical grade for {raw_value!r}: {e}") from e


# ─── Conduct ──────────────────────────────────────────────────
def _build_conduct(
    profile: ProfileBundle,
    raw: dict[str, Any],
    f: _CanonicalFields,
    confidence: float,
) -> CanonicalConduct | None:
    raw_value = raw.get(f.conduct)
    if not raw_value:
        return None
    level = profile.conduct_scale.lookup(str(raw_value))
    if level is None:
        raise MappingError(
            f"unknown conduct {raw_value!r} in scale {profile.conduct_scale.id!r}",
            raw_value=str(raw_value),
            scale_id=profile.conduct_scale.id,
        )
    canonical_level = _conduct_categorical_for(level.normalized)
    return CanonicalConduct(
        level=canonical_level,
        raw_source_value=level.raw_value,
        confidence=min(confidence, level.confidence),
    )


def _conduct_categorical_for(normalized: float) -> CanonicalConductLevel:
    """Conduct uses the same 6-level shape as grades but its own enum.

    Lower bounds match :data:`CanonicalGradeLevel`'s; only the labels differ.
    """
    bounds: list[tuple[float, CanonicalConductLevel]] = [
        (0.0, CanonicalConductLevel.REPREHENSIBLE),
        (1 / 6, CanonicalConductLevel.INAPPROPRIATE),
        (2 / 6, CanonicalConductLevel.ACCEPTABLE),
        (3 / 6, CanonicalConductLevel.GOOD),
        (4 / 6, CanonicalConductLevel.VERY_GOOD),
        (5 / 6, CanonicalConductLevel.EXEMPLARY),
    ]
    chosen = bounds[0][1]
    eps = 1e-9
    for lo, lvl in bounds:
        if normalized + eps >= lo:
            chosen = lvl
    return chosen


# ─── Religion / Ethics ────────────────────────────────────────
def _build_religion_ethics(
    profile: ProfileBundle,
    raw: dict[str, Any],
    f: _CanonicalFields,
    confidence: float,
) -> CanonicalGrade | None:
    """Returns the religion/ethics grade, or None if absent.

    Caller controls inclusion via ``include_religion_ethics``. Validation
    of the lawful basis is the API layer's job (Phase 6).
    """
    raw_value = raw.get(f.religion_ethics)
    if not raw_value:
        return None
    return _resolve_grade(profile.grade_scale, str(raw_value), confidence)


# ─── Helpers ──────────────────────────────────────────────────
def _required_str(raw: dict[str, Any], key: str, *, context: str = "") -> str:
    value = raw.get(key)
    if value is None or (isinstance(value, str) and not value.strip()):
        suffix = f" in {context}" if context else ""
        raise MappingError(f"required field {key!r} missing or empty{suffix}", field=key)
    return str(value).strip()


def _parse_date(value: Any, field_name: str) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError as e:
            raise MappingError(
                f"invalid ISO date for {field_name!r}: {value!r}",
                field=field_name,
            ) from e
    raise MappingError(
        f"unsupported date type for {field_name!r}: {type(value).__name__}",
        field=field_name,
    )


# Suppress unused-import warning — re-exported via the public list above.
_ = CanonicalGradeLevel

__all__ = ["CANONICAL_EXTRACTION_FIELDS", "extract_to_canonical"]

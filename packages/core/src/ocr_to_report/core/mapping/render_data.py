"""Canonical IR + target bundle → flat ``{cell_ref → value}`` map.

The Phase 4 openpyxl renderer takes the produced :class:`RenderData` and
writes each cell into the target's xlsx template. Keeping this layer pure
lets us snapshot-test the mapping independently of the Excel I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ocr_to_report.core.errors.domain import MappingError
from ocr_to_report.core.target.templates import (
    TargetTemplate,
    TemplateBindingKind,
    TemplateCellBinding,
)

if TYPE_CHECKING:
    from ocr_to_report.core.canonical.subject import CanonicalSubject
    from ocr_to_report.core.canonical.transcript import CanonicalTranscript
    from ocr_to_report.core.enums.canonical import CanonicalSubjectId
    from ocr_to_report.core.target.bundle import TargetBundle


# Cell values are restricted to JSON-serializable atoms plus the explicit
# "no value" placeholder ``None`` (which the renderer skips).
RenderCellValue = str | int | float | bool | None


@dataclass(frozen=True, slots=True)
class RenderData:
    """Output of :func:`canonical_to_render_data`.

    Carries:

    * ``template_key`` — which template the renderer should fill.
    * ``cells`` — A1-style cell reference → value.
    * ``warnings`` — non-fatal mapping issues (e.g., unrecognized subject;
      hours unknown for a target year).
    """

    template_key: str
    cells: dict[str, RenderCellValue]
    warnings: list[str] = field(default_factory=list)


def canonical_to_render_data(
    target: TargetBundle,
    transcript: CanonicalTranscript,
    *,
    template_override_key: str | None = None,
) -> RenderData:
    """Turn a canonical transcript into a renderer-ready cell map.

    Selects the template by ``transcript.student.target_year_index`` unless
    ``template_override_key`` is provided. Raises :class:`MappingError` if
    no matching template exists.
    """
    template = _select_template(target, transcript, template_override_key)

    by_canonical: dict[CanonicalSubjectId, CanonicalSubject] = {}
    for s in transcript.subjects:
        if s.canonical_id is not None and s.canonical_id not in by_canonical:
            by_canonical[s.canonical_id] = s

    warnings: list[str] = []
    cells: dict[str, RenderCellValue] = {}

    for binding in template.bindings:
        try:
            value = _resolve_binding(
                binding=binding,
                target=target,
                transcript=transcript,
                by_canonical=by_canonical,
            )
        except MappingError as e:
            warnings.append(f"{binding.cell}: {e.detail}")
            value = None
        cells[binding.cell] = value

    # Confirm advanced markers cross-validate
    advanced_canon = {
        s.canonical_id for s in transcript.subjects if s.is_advanced and s.canonical_id is not None
    }
    if transcript.advanced_raw_names and not advanced_canon:
        warnings.append(
            "transcript advertises advanced subjects but none were resolved to "
            "canonical ids — check vocabulary"
        )

    return RenderData(template_key=template.key, cells=cells, warnings=warnings)


# ─── Template selection ───────────────────────────────────────
def _select_template(
    target: TargetBundle,
    transcript: CanonicalTranscript,
    template_override_key: str | None,
) -> TargetTemplate:
    if template_override_key is not None:
        for t in target.templates:
            if t.key == template_override_key:
                return t
        raise MappingError(
            f"template_override_key={template_override_key!r} not in target {target.id!r}",
            template_key=template_override_key,
            target_id=target.id,
        )

    target_index_for_just_completed = _target_year_for_source_year(
        target, transcript.student.source_year_index
    )
    for t in target.templates:
        if t.target_year_index == target_index_for_just_completed:
            return t
    raise MappingError(
        f"no template found in target {target.id!r} for target_year="
        f"{target_index_for_just_completed} (source_year_index="
        f"{transcript.student.source_year_index})",
        target_id=target.id,
        target_year=target_index_for_just_completed,
        source_year_index=transcript.student.source_year_index,
    )


def _target_year_for_source_year(target: TargetBundle, source_year_index: int) -> int:
    """Map a source-system year index to the target system's year index.

    For the standard PL→US-HS case this is +8 (1→9, 2→10, ...); other
    systems define their own mapping in year_system.yaml.
    """
    entry = target.year_system.for_source_year(source_year_index)
    if entry is None:
        raise MappingError(
            f"target {target.id!r} has no year for source_year_index={source_year_index}",
            target_id=target.id,
            source_year_index=source_year_index,
        )
    return entry.target_index


# ─── Binding resolution ───────────────────────────────────────
def _resolve_binding(  # noqa: PLR0911 — explicit dispatch on TemplateBindingKind
    *,
    binding: TemplateCellBinding,
    target: TargetBundle,
    transcript: CanonicalTranscript,
    by_canonical: dict[CanonicalSubjectId, CanonicalSubject],
) -> RenderCellValue:
    student = transcript.student
    kind = binding.kind

    if kind is TemplateBindingKind.LITERAL:
        return binding.literal_value
    if kind is TemplateBindingKind.STUDENT_FULL_NAME:
        return student.full_name
    if kind is TemplateBindingKind.STUDENT_BIRTH_DATE:
        return student.birth_date.isoformat() if student.birth_date else None
    if kind is TemplateBindingKind.STUDENT_SCHOOL_YEAR:
        return student.school_year
    if kind is TemplateBindingKind.STUDENT_SCHOOL_NAME:
        return student.school_name
    if kind is TemplateBindingKind.STUDENT_CITY:
        return student.city
    if kind is TemplateBindingKind.STUDENT_REGION:
        return student.region

    if kind in {
        TemplateBindingKind.TARGET_YEAR_DISPLAY,
        TemplateBindingKind.TARGET_NEXT_YEAR_DISPLAY,
    }:
        return _year_display(target, transcript, kind)

    if kind is TemplateBindingKind.SUBJECT_GRADE:
        return _subject_grade(binding, target, by_canonical)
    if kind is TemplateBindingKind.SUBJECT_HOURS:
        return _subject_hours(binding, target, transcript, by_canonical)

    if kind is TemplateBindingKind.CONDUCT_VALUE:
        if transcript.conduct is None or transcript.conduct.raw_source_value is None:
            return None
        return transcript.conduct.raw_source_value

    raise MappingError(f"unhandled binding kind: {kind}")


def _year_display(
    target: TargetBundle,
    transcript: CanonicalTranscript,
    kind: TemplateBindingKind,
) -> str | None:
    student = transcript.student
    src_index = (
        student.source_year_index
        if kind is TemplateBindingKind.TARGET_YEAR_DISPLAY
        else student.target_year_index
    )
    entry = target.year_system.for_source_year(src_index)
    return entry.display_name if entry is not None else None


def _subject_grade(
    binding: TemplateCellBinding,
    target: TargetBundle,
    by_canonical: dict[CanonicalSubjectId, CanonicalSubject],
) -> str | None:
    if binding.subject_id is None:  # validator should have caught this
        raise MappingError("SUBJECT_GRADE binding without subject_id")
    subject = by_canonical.get(binding.subject_id)
    if subject is None or subject.grade is None:
        return None
    target_level = target.grade_scale.for_canonical(subject.grade.level_categorical)
    return target_level.display_value


def _subject_hours(
    binding: TemplateCellBinding,
    target: TargetBundle,
    transcript: CanonicalTranscript,
    by_canonical: dict[CanonicalSubjectId, CanonicalSubject],
) -> str | int | None:
    if binding.subject_id is None:
        raise MappingError("SUBJECT_HOURS binding without subject_id")
    subject = by_canonical.get(binding.subject_id)
    taxonomy_entry = target.subject_taxonomy.for_canonical(binding.subject_id)
    if subject is None or taxonomy_entry is None:
        return None
    # Hours apply to the year the subject was actually taken — i.e., the
    # source's just-completed year, not the next year.
    target_year = _target_year_for_source_year(target, transcript.student.source_year_index)
    base = taxonomy_entry.hours_for_year(target_year)
    if base is None:
        return None
    total = base + (taxonomy_entry.advanced_hour_bonus if subject.is_advanced else 0)
    # Render as "<n>h" string to match the existing US-HS template format.
    return f"{total}h"


__all__ = ["RenderCellValue", "RenderData", "canonical_to_render_data"]

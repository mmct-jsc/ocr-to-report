"""Source profile YAML loader.

A profile bundle is a directory:

    profiles/<id>/
    ├── manifest.yaml
    ├── extraction_schema.yaml
    ├── vocabulary.yaml
    ├── grade_scale.yaml
    ├── conduct_scale.yaml
    ├── year_system.yaml
    └── prompts/extraction.md

YAML format conventions (loader-only, not Pydantic types):

* ``grade_scale.yaml`` and ``conduct_scale.yaml`` levels MAY use either
  ``normalized: <0..1 float>`` directly OR ``canonical: <CanonicalGradeLevel
  name>``. When ``canonical`` is supplied the loader maps it to the
  enum's lower bound. When both are present, ``normalized`` wins and must
  be inside the canonical band.

* All YAML files are validated against their Pydantic models. Any error
  raises :class:`ProfileLoadError` with the file path and a concise reason.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ocr_to_report.core.canonical.grade import _LEVEL_LOWER_BOUNDS, categorical_for
from ocr_to_report.core.enums.canonical import CanonicalGradeLevel
from ocr_to_report.core.errors.domain import OcrToReportError
from ocr_to_report.core.profile.bundle import ProfileBundle
from ocr_to_report.core.profile.extraction_schema import ProfileExtractionSchema
from ocr_to_report.core.profile.grade_scale import (
    ProfileGradeScale,
)
from ocr_to_report.core.profile.manifest import ProfileManifest
from ocr_to_report.core.profile.vocabulary import ProfileVocabulary
from ocr_to_report.core.profile.year_system import ProfileYearSystem


class ProfileLoadError(OcrToReportError):
    """A profile bundle could not be loaded or failed validation."""

    status = 500
    type_uri = "https://errors.ocr-to-report/profile-load-failed"
    title = "Profile bundle load failed"


def load_profile_bundle(bundle_dir: Path) -> ProfileBundle:
    """Load and validate a profile bundle from a directory.

    Raises :class:`ProfileLoadError` (with the offending file in the
    extensions) on any I/O, parse, or validation failure.
    """
    if not bundle_dir.is_dir():
        raise ProfileLoadError(
            f"profile bundle directory not found: {bundle_dir}",
            bundle_dir=str(bundle_dir),
        )

    # YAML provides plain strings/ints for enum fields; non-strict
    # validation lets StrEnum/IntEnum types coerce naturally at load
    # time. Programmatic construction elsewhere remains strict.
    try:
        manifest = ProfileManifest.model_validate(
            _read_yaml(bundle_dir / "manifest.yaml"),
            strict=False,
        )
        extraction_schema = ProfileExtractionSchema.model_validate(
            _read_yaml(bundle_dir / "extraction_schema.yaml"),
            strict=False,
        )
        vocabulary = ProfileVocabulary.model_validate(
            _read_yaml(bundle_dir / "vocabulary.yaml"),
            strict=False,
        )
        grade_scale = _load_grade_scale(bundle_dir / "grade_scale.yaml")
        conduct_scale = _load_grade_scale(bundle_dir / "conduct_scale.yaml")
        year_system = ProfileYearSystem.model_validate(
            _read_yaml(bundle_dir / "year_system.yaml"),
            strict=False,
        )
        prompt_path = bundle_dir / "prompts" / "extraction.md"
        prompt = _read_text(prompt_path)
    except ProfileLoadError:
        raise
    except ValidationError as e:
        raise ProfileLoadError(
            f"validation failed in {bundle_dir}: {e}",
            bundle_dir=str(bundle_dir),
        ) from e
    except (yaml.YAMLError, OSError) as e:
        raise ProfileLoadError(
            f"could not read {bundle_dir}: {e}",
            bundle_dir=str(bundle_dir),
        ) from e

    return ProfileBundle(
        manifest=manifest,
        extraction_schema=extraction_schema,
        vocabulary=vocabulary,
        grade_scale=grade_scale,
        conduct_scale=conduct_scale,
        year_system=year_system,
        extraction_prompt_template=prompt,
    )


# ─── Helpers ──────────────────────────────────────────────────
def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise ProfileLoadError(f"missing required file: {path}", path=str(path))
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ProfileLoadError(f"YAML parse error in {path}: {e}", path=str(path)) from e


def _read_text(path: Path) -> str:
    if not path.is_file():
        raise ProfileLoadError(f"missing required file: {path}", path=str(path))
    try:
        return path.read_text(encoding="utf-8")
    except OSError as e:
        raise ProfileLoadError(f"could not read {path}: {e}", path=str(path)) from e


_CANONICAL_PATTERN = re.compile(r"^[A-Z][A-Z_]+$")


def _load_grade_scale(path: Path) -> ProfileGradeScale:
    """Load a grade-scale YAML, translating ``canonical:`` to ``normalized:``."""
    raw = _read_yaml(path)
    if not isinstance(raw, dict) or "levels" not in raw:
        raise ProfileLoadError(
            f"grade scale {path} must be a dict with a 'levels' key",
            path=str(path),
        )

    out_levels: list[dict[str, Any]] = []
    for i, level_raw in enumerate(raw["levels"]):
        if not isinstance(level_raw, dict):
            raise ProfileLoadError(
                f"grade scale level #{i} in {path} is not a dict",
                path=str(path),
            )
        out_levels.append(_normalize_level(level_raw, path=path, idx=i))

    raw["levels"] = out_levels
    try:
        return ProfileGradeScale.model_validate(raw, strict=False)
    except ValidationError as e:
        raise ProfileLoadError(
            f"grade scale validation failed for {path}: {e}",
            path=str(path),
        ) from e


def _normalize_level(level: dict[str, Any], *, path: Path, idx: int) -> dict[str, Any]:
    """Translate a level dict from YAML form to GradeScaleLevel form.

    Specifically: handles the ``canonical: <NAME>`` shorthand by mapping to
    the enum's lower-bound float on the 0..1 scale.
    """
    out = dict(level)
    canonical_raw = out.pop("canonical", None)
    normalized = out.get("normalized")

    if canonical_raw is None and normalized is None:
        raise ProfileLoadError(
            f"grade scale level #{idx} in {path} must have either 'canonical' or 'normalized'",
            path=str(path),
            level_index=idx,
        )

    if canonical_raw is not None:
        if not isinstance(canonical_raw, str) or not _CANONICAL_PATTERN.match(canonical_raw):
            raise ProfileLoadError(
                f"invalid canonical level {canonical_raw!r} at level #{idx} in {path}",
                path=str(path),
            )
        try:
            level_enum = CanonicalGradeLevel[canonical_raw]
        except KeyError as e:
            valid = ", ".join(c.name for c in CanonicalGradeLevel)
            raise ProfileLoadError(
                f"unknown canonical level {canonical_raw!r} at level #{idx} in {path}; "
                f"valid: {valid}",
                path=str(path),
            ) from e

        if normalized is None:
            out["normalized"] = _LEVEL_LOWER_BOUNDS[level_enum]
        else:
            # both present — verify the explicit normalized lands in the band
            try:
                derived = categorical_for(float(normalized))
            except ValueError as e:
                raise ProfileLoadError(
                    f"invalid normalized {normalized!r} at level #{idx} in {path}: {e}",
                    path=str(path),
                ) from e
            if derived is not level_enum:
                raise ProfileLoadError(
                    f"level #{idx} in {path}: canonical={canonical_raw} but "
                    f"normalized={normalized} lands in {derived.name}",
                    path=str(path),
                )

    return out


__all__ = ["ProfileLoadError", "load_profile_bundle"]

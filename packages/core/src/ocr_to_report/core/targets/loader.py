"""Target bundle YAML loader.

A target bundle is a directory:

    targets/<id>/
    ├── manifest.yaml
    ├── grade_scale.yaml
    ├── conduct_scale.yaml
    ├── year_system.yaml
    ├── subject_taxonomy.yaml
    └── templates/
        ├── grade_9.binding.yaml      (binding spec)
        └── grade_9.xlsx              (the actual template file)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from ocr_to_report.core.enums.canonical import CanonicalGradeLevel
from ocr_to_report.core.errors.domain import OcrToReportError
from ocr_to_report.core.target.bundle import TargetBundle
from ocr_to_report.core.target.grade_scale import TargetGradeScale
from ocr_to_report.core.target.manifest import TargetManifest
from ocr_to_report.core.target.subject_taxonomy import TargetSubjectTaxonomy
from ocr_to_report.core.target.templates import TargetTemplate
from ocr_to_report.core.target.year_system import TargetYearSystem

_BINDING_SUFFIX = ".binding.yaml"


class TargetLoadError(OcrToReportError):
    """A target bundle could not be loaded or failed validation."""

    status = 500
    type_uri = "https://errors.ocr-to-report/target-load-failed"
    title = "Target bundle load failed"


def load_target_bundle(bundle_dir: Path) -> TargetBundle:
    """Load and validate a target bundle from a directory.

    Raises :class:`TargetLoadError` on any I/O, parse, or validation failure.
    """
    if not bundle_dir.is_dir():
        raise TargetLoadError(
            f"target bundle directory not found: {bundle_dir}",
            bundle_dir=str(bundle_dir),
        )

    try:
        manifest = TargetManifest.model_validate(
            _read_yaml(bundle_dir / "manifest.yaml"),
            strict=False,
        )
        grade_scale = TargetGradeScale.model_validate(
            _normalize_grade_scale_yaml(_read_yaml(bundle_dir / "grade_scale.yaml")),
            strict=False,
        )
        conduct_scale = TargetGradeScale.model_validate(
            _normalize_grade_scale_yaml(_read_yaml(bundle_dir / "conduct_scale.yaml")),
            strict=False,
        )
        year_system = TargetYearSystem.model_validate(
            _read_yaml(bundle_dir / "year_system.yaml"),
            strict=False,
        )
        subject_taxonomy = TargetSubjectTaxonomy.model_validate(
            _read_yaml(bundle_dir / "subject_taxonomy.yaml"),
            strict=False,
        )
        templates = _load_templates(bundle_dir / "templates")
    except TargetLoadError:
        raise
    except ValidationError as e:
        raise TargetLoadError(
            f"validation failed in {bundle_dir}: {e}",
            bundle_dir=str(bundle_dir),
        ) from e
    except (yaml.YAMLError, OSError) as e:
        raise TargetLoadError(
            f"could not read {bundle_dir}: {e}",
            bundle_dir=str(bundle_dir),
        ) from e

    return TargetBundle(
        manifest=manifest,
        grade_scale=grade_scale,
        conduct_scale=conduct_scale,
        year_system=year_system,
        subject_taxonomy=subject_taxonomy,
        templates=templates,
    )


def _read_yaml(path: Path) -> Any:
    if not path.is_file():
        raise TargetLoadError(f"missing required file: {path}", path=str(path))
    try:
        with path.open(encoding="utf-8") as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise TargetLoadError(f"YAML parse error in {path}: {e}", path=str(path)) from e


def _normalize_grade_scale_yaml(raw: Any) -> Any:
    """Convert ``canonical_levels: ['EXCELLENT', ...]`` (strings) to the
    underlying IntEnum values so Pydantic validates without name-resolution
    quirks for IntEnum types."""
    if not isinstance(raw, dict):
        raise TargetLoadError("grade scale YAML must be a dict")
    levels = raw.get("levels")
    if not isinstance(levels, list):
        return raw
    for level in levels:
        if not isinstance(level, dict):
            continue
        canon = level.get("canonical_levels")
        if not isinstance(canon, list):
            continue
        translated: list[int] = []
        for item in canon:
            if isinstance(item, str):
                try:
                    translated.append(int(CanonicalGradeLevel[item]))
                except KeyError as e:
                    valid = ", ".join(c.name for c in CanonicalGradeLevel)
                    raise TargetLoadError(
                        f"unknown canonical level {item!r}; valid: {valid}"
                    ) from e
            elif isinstance(item, int):
                translated.append(item)
            else:
                raise TargetLoadError(
                    f"canonical_levels item must be str or int, got {type(item).__name__}"
                )
        level["canonical_levels"] = translated
    return raw


def _load_templates(templates_dir: Path) -> list[TargetTemplate]:
    """Load every ``<key>.binding.yaml`` in the templates directory.

    The binding YAML carries the ``key``, ``output_format``,
    ``target_year_index``, and ``bindings`` list. The actual template file
    (xlsx/pdf/etc.) lives next to it; the binding's ``blob_path`` is
    re-anchored relative to the bundle root for downstream code.
    """
    if not templates_dir.is_dir():
        # A target with zero templates is technically valid (e.g., a
        # JSON-only target). Validation will catch it if a template is
        # required (none currently) — at the bundle level we just return [].
        return []

    out: list[TargetTemplate] = []
    for path in sorted(templates_dir.iterdir()):
        if not path.name.endswith(_BINDING_SUFFIX):
            continue
        raw = _read_yaml(path)
        if not isinstance(raw, dict):
            raise TargetLoadError(
                f"binding spec {path} must be a dict",
                path=str(path),
            )
        # Re-anchor blob_path relative to the bundle root. Always emit a
        # POSIX-style path so identifiers are platform-independent (these
        # are storage keys, not OS paths).
        blob_path = raw.get("blob_path")
        if isinstance(blob_path, str):
            raw["blob_path"] = (Path("templates") / blob_path).as_posix()
        try:
            out.append(TargetTemplate.model_validate(raw, strict=False))
        except ValidationError as e:
            raise TargetLoadError(
                f"template binding validation failed for {path}: {e}",
                path=str(path),
            ) from e
    return out


__all__ = ["TargetLoadError", "load_target_bundle"]

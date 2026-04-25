"""Pipeline YAML loader.

A pipeline YAML looks like:

    id: default_v1
    description: |
      Sync extract -> translate -> render -> notify (no human review)
    steps:
      - id: preprocess
      - id: extract
        config:
          provider_policy: adaptive
          confidence_threshold: 0.85
      - id: translate
      - id: validate
      - id: map
      - id: render
      - id: persist
      - id: notify_webhook

Each step's ``config`` is splatted as kwargs to its factory in the
:class:`StepRegistry`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ocr_to_report.core.errors.domain import OcrToReportError
from ocr_to_report.core.pipeline.engine import Pipeline
from ocr_to_report.core.pipeline.registry import StepRegistry


class PipelineLoadError(OcrToReportError):
    """A pipeline YAML failed to load or validate."""

    status = 500
    type_uri = "https://errors.ocr-to-report/pipeline-load"
    title = "Pipeline load error"


def load_pipeline(path: Path, registry: StepRegistry) -> Pipeline:
    """Load and validate a pipeline YAML; resolve every step against the
    registry.

    Raises :class:`PipelineLoadError` on missing keys, unknown step ids,
    or factory failures.
    """
    if not path.is_file():
        raise PipelineLoadError(f"pipeline file not found: {path}", path=str(path))
    try:
        with path.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise PipelineLoadError(f"YAML parse error in {path}: {e}", path=str(path)) from e

    if not isinstance(data, dict):
        raise PipelineLoadError(f"pipeline YAML must be a dict, got {type(data).__name__}")

    pipeline_id = _required_str(data, "id")
    description = data.get("description") or ""
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise PipelineLoadError(
            f"pipeline {pipeline_id} must have a non-empty 'steps' list",
        )

    steps = []
    for i, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            raise PipelineLoadError(
                f"pipeline {pipeline_id} step #{i} must be a dict",
            )
        step_id = _required_str(raw, "id", f"pipeline {pipeline_id} step #{i}")
        config = raw.get("config") or {}
        if not isinstance(config, dict):
            raise PipelineLoadError(
                f"pipeline {pipeline_id} step {step_id!r} config must be a dict",
            )
        steps.append(registry.build(step_id, config))

    return Pipeline(id=pipeline_id, description=description, steps=steps)


def _required_str(data: dict[str, Any], key: str, context: str = "") -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        suffix = f" in {context}" if context else ""
        raise PipelineLoadError(f"missing or empty required key {key!r}{suffix}")
    return value


__all__ = ["PipelineLoadError", "load_pipeline"]

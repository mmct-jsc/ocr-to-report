"""Pipeline YAML loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from ocr_to_report.core.pipeline import (
    PipelineLoadError,
    StepRegistry,
    load_pipeline,
)
from ocr_to_report.core.steps import register_default_steps

REPO_ROOT = Path(__file__).resolve().parents[3]


def _registry() -> StepRegistry:
    return register_default_steps(StepRegistry())


# ─── Shipped pipelines load ───────────────────────────────────
def test_default_v1_loads() -> None:
    p = load_pipeline(REPO_ROOT / "pipelines" / "default_v1.yaml", _registry())
    assert p.id == "default_v1"
    ids = [s.id for s in p.steps]
    assert ids == [
        "preprocess",
        "detect_profile",
        "extract",
        "translate",
        "validate",
        "map",
        "render",
        "persist",
        "notify_webhook",
    ]


def test_with_manual_review_v1_loads() -> None:
    p = load_pipeline(REPO_ROOT / "pipelines" / "with_manual_review_v1.yaml", _registry())
    ids = [s.id for s in p.steps]
    assert "quality_gate" in ids
    assert "human_review" in ids


def test_batch_economy_v1_loads() -> None:
    p = load_pipeline(REPO_ROOT / "pipelines" / "batch_economy_v1.yaml", _registry())
    assert p.id == "batch_economy_v1"


# ─── Error paths ──────────────────────────────────────────────
def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PipelineLoadError):
        load_pipeline(tmp_path / "nope.yaml", _registry())


def test_missing_id_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("description: x\nsteps:\n  - id: preprocess\n", encoding="utf-8")
    with pytest.raises(PipelineLoadError):
        load_pipeline(p, _registry())


def test_empty_steps_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("id: x\ndescription: y\nsteps: []\n", encoding="utf-8")
    with pytest.raises(PipelineLoadError):
        load_pipeline(p, _registry())


def test_unknown_step_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(
        "id: x\ndescription: y\nsteps:\n  - id: not_a_real_step\n",
        encoding="utf-8",
    )
    with pytest.raises(Exception):  # noqa: B017 — registry raises StepRegistryError
        load_pipeline(p, _registry())


def test_yaml_parse_error_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text(":\n  invalid:: ::\n", encoding="utf-8")
    with pytest.raises(PipelineLoadError):
        load_pipeline(p, _registry())

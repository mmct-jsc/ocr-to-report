"""Phase 4 — pipeline engine, registry, and built-in step unit tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.pipeline import (
    Pipeline,
    PipelineContext,
    PipelineError,
    StepRegistry,
    StepResult,
    StepStatus,
    run_pipeline,
)
from ocr_to_report.core.steps import register_default_steps
from ocr_to_report.core.steps.human_review import HumanReviewStep
from ocr_to_report.core.steps.quality_gate import QualityGateStep


# ─── Engine ───────────────────────────────────────────────────
class _OkStep:
    id: str = "stub_ok"

    def __init__(self, *, key: str = "x", value: str = "v") -> None:
        self.key = key
        self.value = value

    async def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(status=StepStatus.OK, artifacts={self.key: self.value})


class _FailStep:
    id: str = "stub_fail"

    async def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(status=StepStatus.FAIL, error_detail="planned failure")


class _ParkStep:
    id: str = "stub_park"

    async def run(self, ctx: PipelineContext) -> StepResult:
        return StepResult(status=StepStatus.PARK, park_reason="awaiting external")


class _RaiseStep:
    id: str = "stub_raise"

    async def run(self, ctx: PipelineContext) -> StepResult:
        raise RuntimeError("unhandled")


def _ctx() -> PipelineContext:
    return PipelineContext(inputs={}, services={})


@pytest.mark.asyncio
async def test_pipeline_runs_steps_in_order() -> None:
    pipeline = Pipeline(
        id="test",
        description="",
        steps=[_OkStep(key="a", value="1"), _OkStep(key="b", value="2")],
    )
    run = await run_pipeline(pipeline, _ctx())
    assert run.terminal_status is StepStatus.OK
    assert run.artifacts == {"a": "1", "b": "2"}
    assert run.completed_step_ids == ["stub_ok", "stub_ok"]


@pytest.mark.asyncio
async def test_pipeline_aborts_on_fail() -> None:
    pipeline = Pipeline(
        id="test",
        description="",
        steps=[_OkStep(key="a", value="1"), _FailStep(), _OkStep(key="never", value="x")],
    )
    run = await run_pipeline(pipeline, _ctx())
    assert run.terminal_status is StepStatus.FAIL
    assert run.error_detail == "planned failure"
    assert run.failed_step_id == "stub_fail"
    assert run.artifacts == {"a": "1"}


@pytest.mark.asyncio
async def test_pipeline_parks_on_park() -> None:
    pipeline = Pipeline(
        id="test",
        description="",
        steps=[_OkStep(key="a", value="1"), _ParkStep()],
    )
    run = await run_pipeline(pipeline, _ctx())
    assert run.terminal_status is StepStatus.PARK
    assert run.park_reason == "awaiting external"
    assert run.artifacts == {"a": "1"}


@pytest.mark.asyncio
async def test_pipeline_translates_unhandled_exceptions() -> None:
    pipeline = Pipeline(
        id="test",
        description="",
        steps=[_RaiseStep()],
    )
    run = await run_pipeline(pipeline, _ctx())
    assert run.terminal_status is StepStatus.FAIL
    assert run.error_detail is not None
    assert "RuntimeError" in run.error_detail


@pytest.mark.asyncio
async def test_pipeline_rejects_artifact_collision() -> None:
    pipeline = Pipeline(
        id="test",
        description="",
        steps=[_OkStep(key="x", value="1"), _OkStep(key="x", value="2")],
    )
    with pytest.raises(PipelineError):
        await run_pipeline(pipeline, _ctx())


# ─── Registry ─────────────────────────────────────────────────
def test_registry_default_steps() -> None:
    reg = register_default_steps(StepRegistry())
    expected = {
        "preprocess",
        "detect_profile",
        "extract",
        "translate",
        "validate",
        "quality_gate",
        "human_review",
        "map",
        "render",
        "persist",
        "notify_webhook",
    }
    assert expected <= set(reg.ids())


def test_registry_unknown_step_raises() -> None:
    from ocr_to_report.core.pipeline.registry import StepRegistryError  # noqa: PLC0415

    reg = StepRegistry()
    with pytest.raises(StepRegistryError):
        reg.build("unknown")


def test_registry_double_register_rejected() -> None:
    from ocr_to_report.core.pipeline.registry import StepRegistryError  # noqa: PLC0415

    reg = StepRegistry()

    def _factory() -> _OkStep:
        return _OkStep()

    reg.register("x", _factory)
    with pytest.raises(StepRegistryError):
        reg.register("x", _factory)


# ─── QualityGate behaviour ────────────────────────────────────
@pytest.mark.asyncio
async def test_quality_gate_passes_at_threshold() -> None:
    step = QualityGateStep(threshold=0.8)
    ctx = _ctx()
    ctx.artifacts["extraction_result"] = type(
        "ER",
        (),
        {"confidence": 0.85},
    )()
    result = await step.run(ctx)
    assert result.status is StepStatus.OK


@pytest.mark.asyncio
async def test_quality_gate_parks_below_threshold() -> None:
    step = QualityGateStep(threshold=0.95)
    ctx = _ctx()
    ctx.artifacts["extraction_result"] = type(
        "ER",
        (),
        {"confidence": 0.5},
    )()
    result = await step.run(ctx)
    assert result.status is StepStatus.PARK
    assert result.park_reason is not None
    assert "below threshold" in result.park_reason


@pytest.mark.asyncio
async def test_quality_gate_fails_when_configured() -> None:
    step = QualityGateStep(threshold=0.95, on_below="fail")
    ctx = _ctx()
    ctx.artifacts["extraction_result"] = type(
        "ER",
        (),
        {"confidence": 0.5},
    )()
    result = await step.run(ctx)
    assert result.status is StepStatus.FAIL


def test_quality_gate_validates_threshold() -> None:
    with pytest.raises(ValueError):
        QualityGateStep(threshold=1.5)


# ─── HumanReview behaviour ────────────────────────────────────
@pytest.mark.asyncio
async def test_human_review_parks_with_no_decision() -> None:
    step = HumanReviewStep(skip_if_passed_quality_gate=False)
    result = await step.run(_ctx())
    assert result.status is StepStatus.PARK


@pytest.mark.asyncio
async def test_human_review_resumes_on_approval() -> None:
    step = HumanReviewStep(skip_if_passed_quality_gate=False)
    ctx = _ctx()
    ctx.artifacts["human_review_decision"] = "approved"
    result = await step.run(ctx)
    assert result.status is StepStatus.OK


@pytest.mark.asyncio
async def test_human_review_fails_on_rejection() -> None:
    step = HumanReviewStep(skip_if_passed_quality_gate=False)
    ctx = _ctx()
    ctx.artifacts["human_review_decision"] = "rejected"
    result = await step.run(ctx)
    assert result.status is StepStatus.FAIL

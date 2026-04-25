"""Pipeline engine — runs an ordered list of steps over a context."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ocr_to_report.core.errors.domain import OcrToReportError
from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)

if TYPE_CHECKING:
    from ocr_to_report.core.pipeline.protocol import Step


class PipelineError(OcrToReportError):
    """A step failed or violated the protocol."""

    status = 500
    type_uri = "https://errors.ocr-to-report/pipeline"
    title = "Pipeline error"


@dataclass(slots=True)
class Pipeline:
    """An ordered, named sequence of steps."""

    id: str
    description: str
    steps: list[Step]


@dataclass(slots=True)
class PipelineRun:
    """The result of running a pipeline.

    Includes the final artifacts (whatever the last successful step
    produced), per-step metrics, accumulated warnings, and the terminal
    state (completed / parked / failed).
    """

    pipeline_id: str
    artifacts: dict[str, object]
    metrics: list[tuple[str, StepMetrics]]
    warnings: list[str]
    terminal_status: StepStatus
    park_reason: str | None = None
    error_detail: str | None = None
    failed_step_id: str | None = None
    completed_step_ids: list[str] = field(default_factory=list)


async def run_pipeline(pipeline: Pipeline, ctx: PipelineContext) -> PipelineRun:
    """Run all steps in order. Aborts on the first FAIL or PARK.

    The context is mutated as the run progresses (new artifacts merged
    in, metrics appended). On FAIL or PARK the partial state is preserved
    in the returned run object so the caller can persist it.
    """
    completed: list[str] = []

    for step in pipeline.steps:
        start = time.monotonic()
        try:
            result: StepResult = await step.run(ctx)
        except OcrToReportError as e:
            duration = (time.monotonic() - start) * 1000
            metrics = StepMetrics(duration_ms=duration)
            ctx.metrics.append((step.id, metrics))
            return PipelineRun(
                pipeline_id=pipeline.id,
                artifacts=dict(ctx.artifacts),
                metrics=list(ctx.metrics),
                warnings=list(ctx.warnings),
                terminal_status=StepStatus.FAIL,
                error_detail=e.detail or str(e),
                failed_step_id=step.id,
                completed_step_ids=completed,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            metrics = StepMetrics(duration_ms=duration)
            ctx.metrics.append((step.id, metrics))
            return PipelineRun(
                pipeline_id=pipeline.id,
                artifacts=dict(ctx.artifacts),
                metrics=list(ctx.metrics),
                warnings=list(ctx.warnings),
                terminal_status=StepStatus.FAIL,
                error_detail=f"unhandled {type(e).__name__}: {e}",
                failed_step_id=step.id,
                completed_step_ids=completed,
            )

        # Always record metrics, regardless of status
        duration = (time.monotonic() - start) * 1000
        if result.metrics.duration_ms == 0.0:
            result_metrics = StepMetrics(
                duration_ms=duration,
                tokens_input=result.metrics.tokens_input,
                tokens_output=result.metrics.tokens_output,
                usd_cost=result.metrics.usd_cost,
                confidence=result.metrics.confidence,
            )
        else:
            result_metrics = result.metrics
        ctx.metrics.append((step.id, result_metrics))
        ctx.warnings.extend(result.warnings)

        if result.status is StepStatus.FAIL:
            return PipelineRun(
                pipeline_id=pipeline.id,
                artifacts=dict(ctx.artifacts),
                metrics=list(ctx.metrics),
                warnings=list(ctx.warnings),
                terminal_status=StepStatus.FAIL,
                error_detail=result.error_detail,
                failed_step_id=step.id,
                completed_step_ids=completed,
            )
        if result.status is StepStatus.PARK:
            return PipelineRun(
                pipeline_id=pipeline.id,
                artifacts=dict(ctx.artifacts),
                metrics=list(ctx.metrics),
                warnings=list(ctx.warnings),
                terminal_status=StepStatus.PARK,
                park_reason=result.park_reason,
                failed_step_id=step.id,
                completed_step_ids=completed,
            )

        # OK or SKIP: merge artifacts and continue.
        for key, value in result.artifacts.items():
            if key in ctx.artifacts:
                raise PipelineError(
                    f"step {step.id!r} produced artifact {key!r} that already exists",
                    step_id=step.id,
                    artifact_key=key,
                )
            ctx.artifacts[key] = value
        completed.append(step.id)

    return PipelineRun(
        pipeline_id=pipeline.id,
        artifacts=dict(ctx.artifacts),
        metrics=list(ctx.metrics),
        warnings=list(ctx.warnings),
        terminal_status=StepStatus.OK,
        completed_step_ids=completed,
    )


__all__ = ["Pipeline", "PipelineError", "PipelineRun", "run_pipeline"]

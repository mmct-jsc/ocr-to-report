"""Render step — fill the target template with render data."""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class RenderStep:
    """Produce the final output blob (xlsx/pdf/etc.).

    Service required: ``renderer`` — a callable
    ``(target_bundle, render_data) -> bytes``.
    Reads:
        - ``target_bundle`` (:class:`TargetBundle`)
        - ``render_data`` (:class:`RenderData`)
    Produces:
        - ``output_blob`` (bytes)
        - ``output_format`` (str, e.g., 'xlsx')
    """

    id: str = "render"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            renderer = ctx.service("renderer")
            target_bundle = ctx.require("target_bundle")
            render_data = ctx.require("render_data")
            blob = renderer(target_bundle, render_data)
            template = next(
                (t for t in target_bundle.templates if t.key == render_data.template_key),
                None,
            )
            output_format = template.output_format if template is not None else "xlsx"
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"render failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={
                "output_blob": blob,
                "output_format": output_format,
            },
            metrics=StepMetrics(duration_ms=duration),
        )


def render_step_factory() -> RenderStep:
    return RenderStep()


__all__ = ["RenderStep", "render_step_factory"]

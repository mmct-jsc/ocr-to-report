"""Map step — canonical transcript + target bundle → render data."""

from __future__ import annotations

import time

from ocr_to_report.core.mapping import canonical_to_render_data
from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class MapToTargetStep:
    """Build the renderer-ready cell map.

    Service required: ``target_registry`` — :class:`TargetRegistry`.
    Reads:
        - ``canonical_transcript`` (:class:`CanonicalTranscript`)
        - ``target_id`` (str, from inputs)
        - ``target_template_key`` (optional, from inputs)
    Produces:
        - ``target_bundle`` (:class:`TargetBundle`)
        - ``render_data`` (:class:`RenderData`)
    """

    id: str = "map"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            registry = ctx.service("target_registry")
            transcript = ctx.require("canonical_transcript")
            target_id = ctx.require("target_id")
            template_override = ctx.get("target_template_key")
            target_bundle = registry.get(target_id)
            render_data = canonical_to_render_data(
                target_bundle,
                transcript,
                template_override_key=template_override,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"map failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={
                "target_bundle": target_bundle,
                "render_data": render_data,
            },
            metrics=StepMetrics(duration_ms=duration),
            warnings=list(render_data.warnings),
        )


def map_to_target_step_factory() -> MapToTargetStep:
    return MapToTargetStep()


__all__ = ["MapToTargetStep", "map_to_target_step_factory"]

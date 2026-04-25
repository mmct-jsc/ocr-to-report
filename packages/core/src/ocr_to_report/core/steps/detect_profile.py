"""Detect-profile step — pick the source profile bundle.

For MVP this just looks up the explicit ``profile_id`` from inputs. A
future enhancement (post-MVP) will use the profile fingerprint patterns
to auto-detect when ``profile_id`` is None.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class DetectProfileStep:
    """Look up the source profile bundle by id.

    Service required: ``profile_registry`` — :class:`ProfileRegistry`.
    Inputs: ``profile_id`` (str).
    Produces artifact: ``profile_bundle`` (:class:`ProfileBundle`).
    """

    id: str = "detect_profile"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            registry = ctx.service("profile_registry")
            profile_id = ctx.require("profile_id")
            bundle = registry.get(profile_id)
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"detect_profile failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={"profile_bundle": bundle},
            metrics=StepMetrics(duration_ms=duration),
        )


def detect_profile_step_factory() -> DetectProfileStep:
    return DetectProfileStep()


__all__ = ["DetectProfileStep", "detect_profile_step_factory"]

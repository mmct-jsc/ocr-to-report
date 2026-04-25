"""Preprocess step — image preprocessing.

Reads ``raw_input_blob`` from inputs, runs it through the
``image_preprocessor`` service (a callable ``bytes -> list[bytes]``), and
produces ``preprocessed_images`` artifact.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class PreprocessStep:
    """Image preprocessing step.

    Service required: ``image_preprocessor`` — a callable
    ``(bytes) -> list[bytes]``.
    Inputs: ``raw_input_blob`` (bytes).
    Produces artifact: ``preprocessed_images`` (list[bytes]).
    """

    id: str = "preprocess"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            preprocessor = ctx.service("image_preprocessor")
            blob = ctx.require("raw_input_blob")
            if not isinstance(blob, (bytes, bytearray)):
                return StepResult(
                    status=StepStatus.FAIL,
                    error_detail=f"raw_input_blob must be bytes, got {type(blob).__name__}",
                )
            images = preprocessor(bytes(blob))
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"preprocess failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={"preprocessed_images": images},
            metrics=StepMetrics(duration_ms=duration),
        )


def preprocess_step_factory() -> PreprocessStep:
    return PreprocessStep()


__all__ = ["PreprocessStep", "preprocess_step_factory"]

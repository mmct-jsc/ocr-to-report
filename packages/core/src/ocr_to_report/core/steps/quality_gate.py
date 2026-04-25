"""Quality-gate step — branch based on extraction confidence."""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class QualityGateStep:
    """Park (or pass) the run based on confidence threshold.

    Configuration:
        - ``threshold`` (float): minimum overall confidence to proceed.
        - ``on_below``: ``"park_for_review"`` (default — emits PARK so
          the caller can route to manual review) or ``"fail"`` (emits
          FAIL with detail).

    Reads ``canonical_transcript`` (or ``extraction_result`` as fallback).
    """

    id: str = "quality_gate"

    def __init__(
        self,
        *,
        threshold: float = 0.85,
        on_below: str = "park_for_review",
    ) -> None:
        if not 0.0 <= threshold <= 1.0:
            raise ValueError("threshold must be in [0, 1]")
        if on_below not in {"park_for_review", "fail"}:
            raise ValueError(f"on_below must be 'park_for_review' or 'fail', got {on_below!r}")
        self._threshold = threshold
        self._on_below = on_below

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        transcript = ctx.get("canonical_transcript")
        extraction_result = ctx.get("extraction_result")
        confidence = (
            transcript.overall_confidence
            if transcript is not None
            else extraction_result.confidence
            if extraction_result is not None
            else None
        )

        if confidence is None:
            return StepResult(
                status=StepStatus.FAIL,
                error_detail=(
                    "quality_gate could not find canonical_transcript or "
                    "extraction_result in the pipeline context"
                ),
            )

        duration = (time.monotonic() - start) * 1000
        metrics = StepMetrics(duration_ms=duration, confidence=confidence)

        if confidence >= self._threshold:
            return StepResult(status=StepStatus.OK, metrics=metrics)

        msg = f"confidence {confidence:.2f} below threshold {self._threshold:.2f}"
        if self._on_below == "park_for_review":
            return StepResult(
                status=StepStatus.PARK,
                metrics=metrics,
                park_reason=msg,
                warnings=[msg],
            )
        return StepResult(status=StepStatus.FAIL, metrics=metrics, error_detail=msg)


def quality_gate_step_factory(**kwargs: object) -> QualityGateStep:
    return QualityGateStep(**kwargs)  # type: ignore[arg-type]


__all__ = ["QualityGateStep", "quality_gate_step_factory"]

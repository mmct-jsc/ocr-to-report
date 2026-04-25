"""Validate step — final invariant check.

Pydantic v2 already enforces every invariant in
:class:`CanonicalTranscript` and friends, so this step is mostly a
marker that surfaces explicit warnings if invariants would have
otherwise failed silently. Use it to add SLA-tier-specific cross-
validation (e.g., "every required subject for the target year was
extracted") without modifying the canonical types.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class ValidateStep:
    """Final invariant check on the canonical transcript.

    Reads ``canonical_transcript``. Produces no new artifacts; emits
    warnings. Fails only on validation errors that would corrupt
    downstream stages.
    """

    id: str = "validate"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        warnings: list[str] = []
        try:
            transcript = ctx.require("canonical_transcript")
            # Accumulate transcript warnings; nothing else to do — the
            # Pydantic model would have raised already if invariants
            # weren't satisfied.
            warnings.extend(transcript.extraction_warnings)
            if not transcript.subjects:
                warnings.append("transcript has no subject rows")
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"validate failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            metrics=StepMetrics(duration_ms=duration),
            warnings=warnings,
        )


def validate_step_factory() -> ValidateStep:
    return ValidateStep()


__all__ = ["ValidateStep", "validate_step_factory"]

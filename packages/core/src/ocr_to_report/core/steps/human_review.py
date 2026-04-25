"""Human-review step — parks the run pending manual approval.

When this step runs in a pipeline (e.g., ``with_manual_review_v1``),
the engine returns control to the caller in PARK state. The caller
persists the partial run and surfaces a review queue entry; once a
reviewer approves via the API, the caller resumes the pipeline from
the next step (Phase 6+ wires the API endpoint).

If the prior :class:`QualityGateStep` already passed (high confidence),
this step is a no-op — set ``skip_if_passed_quality_gate`` true (the
default) to short-circuit. Otherwise it always parks.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class HumanReviewStep:
    """Always-park (or skip) gate awaiting external approval."""

    id: str = "human_review"

    def __init__(self, *, skip_if_passed_quality_gate: bool = True) -> None:
        self._skip_if_passed = skip_if_passed_quality_gate

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        # If a quality_gate step ran and emitted no PARK, we're past it
        # already — skip review. Detect by looking for the literal flag
        # the caller sets in artifacts after resuming a parked review.
        if self._skip_if_passed and ctx.get("quality_gate_passed"):
            return StepResult(
                status=StepStatus.SKIP,
                metrics=StepMetrics(duration_ms=(time.monotonic() - start) * 1000),
            )

        # If the caller resumed after approval, they should set
        # ``human_review_decision`` in inputs/artifacts. We treat its
        # presence as "approved, continue".
        decision = ctx.get("human_review_decision")
        if decision == "approved":
            return StepResult(
                status=StepStatus.OK,
                metrics=StepMetrics(duration_ms=(time.monotonic() - start) * 1000),
                warnings=["human_review: approved by reviewer"],
            )
        if decision == "rejected":
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=(time.monotonic() - start) * 1000),
                error_detail="human_review: rejected by reviewer",
            )

        # No decision yet — park.
        return StepResult(
            status=StepStatus.PARK,
            metrics=StepMetrics(duration_ms=(time.monotonic() - start) * 1000),
            park_reason="awaiting human review approval",
        )


def human_review_step_factory(**kwargs: object) -> HumanReviewStep:
    return HumanReviewStep(**kwargs)  # type: ignore[arg-type]


__all__ = ["HumanReviewStep", "human_review_step_factory"]

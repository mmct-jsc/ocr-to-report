"""Persist step — store the run's outputs to the configured backend.

Phase 4: no-op pass-through (logs a warning). Phase 5 wires up the
blob-store + database services and writes:

* the input PDF (encrypted blob)
* the canonical transcript (encrypted column)
* the output xlsx (blob)
* a hash-chained audit log entry

Until then, this step exists so pipelines that include it (default_v1
and with_manual_review_v1) load and run cleanly.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class PersistStep:
    """No-op pass-through; Phase 5 wires the actual storage."""

    id: str = "persist"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.SKIP,
            metrics=StepMetrics(duration_ms=duration),
            warnings=["persist step is a no-op until Phase 5 wires storage"],
        )


def persist_step_factory() -> PersistStep:
    return PersistStep()


__all__ = ["PersistStep", "persist_step_factory"]

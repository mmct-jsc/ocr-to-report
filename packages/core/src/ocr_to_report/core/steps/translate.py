"""Translate step — raw extraction → CanonicalTranscript."""

from __future__ import annotations

import time

from ocr_to_report.core.mapping import extract_to_canonical
from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class TranslateStep:
    """Convert profile-shaped raw extraction → :class:`CanonicalTranscript`.

    Reads:
        - ``raw_extraction`` (dict[str, Any])
        - ``profile_bundle`` (:class:`ProfileBundle`)
        - ``extraction_result`` (:class:`ExtractionResult`) — for confidence

    Produces:
        - ``canonical_transcript`` (:class:`CanonicalTranscript`)
    """

    id: str = "translate"

    def __init__(self, *, include_religion_ethics: bool = False) -> None:
        self._include_religion_ethics = include_religion_ethics

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            raw = ctx.require("raw_extraction")
            profile_bundle = ctx.require("profile_bundle")
            extraction_result = ctx.get("extraction_result")
            extraction_confidence = (
                extraction_result.confidence if extraction_result is not None else 1.0
            )
            transcript = extract_to_canonical(
                profile_bundle,
                raw,
                extraction_confidence=extraction_confidence,
                include_religion_ethics=self._include_religion_ethics,
            )
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"translate failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={"canonical_transcript": transcript},
            metrics=StepMetrics(
                duration_ms=duration,
                confidence=transcript.overall_confidence,
            ),
            warnings=list(transcript.extraction_warnings),
        )


def translate_step_factory(**kwargs: object) -> TranslateStep:
    return TranslateStep(**kwargs)  # type: ignore[arg-type]


__all__ = ["TranslateStep", "translate_step_factory"]

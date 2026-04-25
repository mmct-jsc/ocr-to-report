"""Notify-webhook step — fire registered webhooks for this tenant.

Phase 4: no-op (logs a warning). Phase 6 wires the webhook publisher
service that signs payloads with HMAC-SHA256 and retries with backoff.
"""

from __future__ import annotations

import time

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


class NotifyWebhookStep:
    """No-op pass-through; Phase 6 wires real webhook delivery."""

    id: str = "notify_webhook"

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.SKIP,
            metrics=StepMetrics(duration_ms=duration),
            warnings=["notify_webhook step is a no-op until Phase 6 wires delivery"],
        )


def notify_webhook_step_factory() -> NotifyWebhookStep:
    return NotifyWebhookStep()


__all__ = ["NotifyWebhookStep", "notify_webhook_step_factory"]

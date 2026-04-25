"""Anthropic Batch API adapter — economy lane (~50% cheaper).

The Batch API takes up to 10,000 message requests in a single call,
processes them within 24 hours, and bills at half the synchronous rate.
We use it for the ``batch_economy_v1`` pipeline: tenants on
non-time-sensitive workflows (admission-season backlogs) submit large
volumes overnight and pick up results the next morning.

Lifecycle exposed by this adapter:

1. :meth:`submit` — POST a list of :class:`VisionRequest` objects with
   per-request ``custom_id`` keys. Returns a :class:`BatchHandle`.
2. :meth:`get_status` — poll a batch by id; returns its current
   :class:`BatchStatus` (in_progress / ended / canceled / errored).
3. :meth:`fetch_results` — once ended, download the JSONL result stream
   and parse it into a ``dict[custom_id, BatchItemResult]``. Each item is
   either an :class:`ExtractionResult` or a per-item error message.

The adapter intentionally does NOT loop; the *worker* drives the polling
cycle (BATCH_POLL tasks rescheduled on the queue with backoff). Keeping
the adapter side-effect-bounded makes the unit tests trivially fast.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final, cast

from ocr_to_report.adapters.vision.anthropic_adapter import (
    _attach_cost,
    _unwrap_response,
    _wrap_schema,
)
from ocr_to_report.adapters.vision.protocol import (
    ExtractionResult,
    TokenUsage,
    VisionProvider,
    VisionRequest,
)
from ocr_to_report.core.errors.domain import VisionProviderError

if TYPE_CHECKING:
    from anthropic import AsyncAnthropic


_BATCH_INPUT_DISCOUNT: Final[float] = 0.5
"""Anthropic bills batch requests at 50% of the standard rate."""

_DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 4096


class BatchStatus(StrEnum):
    """High-level batch state, normalized across SDK shape variations."""

    IN_PROGRESS = "in_progress"
    ENDED = "ended"
    CANCELED = "canceled"
    EXPIRED = "expired"
    ERRORED = "errored"


@dataclass(frozen=True, slots=True)
class BatchHandle:
    """Reference to a submitted batch.

    Attributes:
        batch_id: Provider-assigned id; survives across processes.
        custom_ids: The set of ``custom_id`` keys submitted with this
            batch. Persisted alongside the batch row so the worker can
            reconcile results back to jobs even after a restart.
        submitted_at: When the batch was POSTed.
    """

    batch_id: str
    custom_ids: list[str]
    submitted_at: datetime


@dataclass(frozen=True, slots=True)
class BatchItemResult:
    """Per-item result of a finished batch.

    Exactly one of :attr:`extraction` or :attr:`error_detail` is set.
    """

    custom_id: str
    extraction: ExtractionResult | None
    error_detail: str | None

    @property
    def is_success(self) -> bool:
        return self.extraction is not None


class AnthropicBatchAdapter:
    """Submit + poll + fetch results from the Anthropic Batch API.

    Args:
        client: An :class:`anthropic.AsyncAnthropic` client.
        model: Model used for every request in a batch. Must support
            structured outputs (``output_config.format``).
        max_output_tokens: Per-request output cap.
    """

    def __init__(
        self,
        client: AsyncAnthropic,
        *,
        model: str = "claude-haiku-4-5",
        max_output_tokens: int = _DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> None:
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    # ─── Submit ──────────────────────────────────────────────
    async def submit(
        self,
        requests: list[tuple[str, VisionRequest]],
    ) -> BatchHandle:
        """Submit a batch.

        Args:
            requests: List of ``(custom_id, vision_request)`` pairs. The
                custom_id is what we use to map results back to jobs
                — typically the job id.

        Returns:
            A :class:`BatchHandle` to be persisted on the batch row.

        Raises:
            VisionProviderError: On any provider-side error.
        """
        if not requests:
            raise VisionProviderError(
                "cannot submit an empty batch",
                model=self._model,
            )

        batch_requests = [
            {
                "custom_id": custom_id,
                "params": self._params_for(req),
            }
            for custom_id, req in requests
        ]
        custom_ids = [cid for cid, _ in requests]

        try:
            import anthropic  # noqa: PLC0415

            batch = await self._client.messages.batches.create(
                requests=cast("Any", batch_requests),
            )
        except (
            anthropic.APIStatusError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as e:
            raise VisionProviderError(
                f"Anthropic Batch submit failed: {e}",
                model=self._model,
            ) from e

        from datetime import UTC, datetime  # noqa: PLC0415

        return BatchHandle(
            batch_id=batch.id,
            custom_ids=custom_ids,
            submitted_at=datetime.now(tz=UTC),
        )

    # ─── Poll ─────────────────────────────────────────────────
    async def get_status(self, batch_id: str) -> BatchStatus:
        """Return the current high-level status of a batch."""
        try:
            import anthropic  # noqa: PLC0415

            batch = await self._client.messages.batches.retrieve(batch_id)
        except (
            anthropic.APIStatusError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as e:
            raise VisionProviderError(
                f"Anthropic Batch retrieve failed: {e}",
                model=self._model,
                batch_id=batch_id,
            ) from e

        return _normalize_status(batch.processing_status)

    # ─── Fetch ────────────────────────────────────────────────
    async def fetch_results(self, handle: BatchHandle) -> dict[str, BatchItemResult]:
        """Download the JSONL result stream and parse per-item results.

        Returns:
            ``{custom_id: BatchItemResult}`` covering every item in the
            batch. Items missing from the stream (extremely rare; only
            seen when the batch was canceled) are populated with an
            error indicating they were dropped.
        """
        try:
            import anthropic  # noqa: PLC0415

            stream = await self._client.messages.batches.results(handle.batch_id)
        except (
            anthropic.APIStatusError,
            anthropic.APIConnectionError,
            anthropic.APITimeoutError,
        ) as e:
            raise VisionProviderError(
                f"Anthropic Batch results fetch failed: {e}",
                model=self._model,
                batch_id=handle.batch_id,
            ) from e

        results: dict[str, BatchItemResult] = {}
        async for entry in stream:
            parsed = self._parse_entry(entry)
            results[parsed.custom_id] = parsed

        for custom_id in handle.custom_ids:
            if custom_id not in results:
                results[custom_id] = BatchItemResult(
                    custom_id=custom_id,
                    extraction=None,
                    error_detail="missing from batch result stream (likely canceled)",
                )
        return results

    async def aclose(self) -> None:
        return None

    # ─── Internals ────────────────────────────────────────────
    def _params_for(self, request: VisionRequest) -> dict[str, Any]:
        """Build the per-request ``params`` payload for a batch entry."""
        wrapped = _wrap_schema(request.output_schema)

        image_blocks = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": base64.standard_b64encode(img).decode("ascii"),
                },
            }
            for img in request.images
        ]
        system_blocks = [
            {"type": "text", "text": request.prompt},
            {
                "type": "text",
                "text": (
                    "Always return JSON matching this schema. The "
                    "`_meta` field is REQUIRED — populate `confidence` "
                    "honestly based on document quality, and list any "
                    "uncertainties under `warnings`.\n\n"
                    f"```json\n{json.dumps(wrapped, sort_keys=True)}\n```"
                ),
            },
        ]
        return {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "system": system_blocks,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        *image_blocks,
                        {
                            "type": "text",
                            "text": (
                                "Extract the requested data from the "
                                "image(s) above. Return JSON only — "
                                "no prose, no markdown."
                            ),
                        },
                    ],
                },
            ],
            "output_config": {"format": {"type": "json_schema", "schema": wrapped}},
        }

    def _parse_entry(self, entry: Any) -> BatchItemResult:
        """Convert one streaming result entry into a :class:`BatchItemResult`."""
        custom_id = getattr(entry, "custom_id", None) or ""
        result_obj = getattr(entry, "result", None)
        if result_obj is None:
            return BatchItemResult(
                custom_id=custom_id,
                extraction=None,
                error_detail="empty result entry",
            )
        result_type = getattr(result_obj, "type", None)
        if result_type != "succeeded":
            err = getattr(result_obj, "error", None) or getattr(result_obj, "message", None) or ""
            return BatchItemResult(
                custom_id=custom_id,
                extraction=None,
                error_detail=f"batch item {result_type}: {err}",
            )
        message = getattr(result_obj, "message", None)
        if message is None:
            return BatchItemResult(
                custom_id=custom_id,
                extraction=None,
                error_detail="batch item succeeded but had no message",
            )
        try:
            extraction = self._build_result(message)
        except VisionProviderError as e:
            return BatchItemResult(
                custom_id=custom_id,
                extraction=None,
                error_detail=str(e),
            )
        return BatchItemResult(
            custom_id=custom_id,
            extraction=extraction,
            error_detail=None,
        )

    def _build_result(self, message: Any) -> ExtractionResult:
        """Convert a batch-message into our :class:`ExtractionResult`."""
        text = _concatenate_text(message)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            raise VisionProviderError(
                f"batch returned non-JSON: {e}",
                model=self._model,
                response_preview=text[:500],
            ) from e
        if not isinstance(payload, dict):
            raise VisionProviderError(
                f"batch returned a {type(payload).__name__}, expected an object",
                model=self._model,
            )
        raw_extraction, confidence, field_confidences, warnings = _unwrap_response(payload)

        usage_obj = getattr(message, "usage", None)
        usage = TokenUsage(
            input_tokens=getattr(usage_obj, "input_tokens", 0) or 0,
            output_tokens=getattr(usage_obj, "output_tokens", 0) or 0,
            cache_creation_input_tokens=getattr(usage_obj, "cache_creation_input_tokens", 0) or 0,
            cache_read_input_tokens=getattr(usage_obj, "cache_read_input_tokens", 0) or 0,
        )
        usage = _attach_cost(usage, self._model)
        # Apply the 50% batch discount on the standard cost.
        usage = TokenUsage(
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_input_tokens=usage.cache_creation_input_tokens,
            cache_read_input_tokens=usage.cache_read_input_tokens,
            usd_cost=usage.usd_cost * _BATCH_INPUT_DISCOUNT,
        )
        return ExtractionResult(
            raw_extraction=raw_extraction,
            confidence=confidence,
            field_confidences=field_confidences,
            warnings=warnings,
            provider=VisionProvider.ANTHROPIC,
            model_id=self._model,
            usage=usage,
        )


def _normalize_status(value: str | None) -> BatchStatus:
    """Map an SDK ``processing_status`` string to our enum."""
    mapping = {
        "in_progress": BatchStatus.IN_PROGRESS,
        "ended": BatchStatus.ENDED,
        "canceled": BatchStatus.CANCELED,
        "cancelled": BatchStatus.CANCELED,
        "expired": BatchStatus.EXPIRED,
        "errored": BatchStatus.ERRORED,
    }
    if value is None:
        return BatchStatus.IN_PROGRESS
    return mapping.get(value, BatchStatus.IN_PROGRESS)


def _concatenate_text(message: Any) -> str:
    """Concatenate every text block in a batch-message response."""
    content = getattr(message, "content", None) or []
    parts: list[str] = []
    for block in content:
        if getattr(block, "type", None) == "text":
            text = getattr(block, "text", "")
            if text:
                parts.append(text)
    if not parts:
        raise VisionProviderError(
            "batch message contained no text blocks",
            model=getattr(message, "model", ""),
        )
    return "".join(parts)


__all__ = [
    "AnthropicBatchAdapter",
    "BatchHandle",
    "BatchItemResult",
    "BatchStatus",
]

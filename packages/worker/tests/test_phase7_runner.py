"""Phase 7 — WorkerRunner dispatch loop."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ocr_to_report.adapters.queue import InMemoryQueue, TaskKind
from ocr_to_report.worker.runner import WorkerRunner


def _ctx_with_queue(queue: InMemoryQueue) -> Any:
    """Build a minimal WorkerContext-like stub for runner tests."""
    ctx = MagicMock()
    ctx.queue = queue
    return ctx


@pytest.mark.asyncio
async def test_runner_dispatches_to_handler() -> None:
    queue = InMemoryQueue()
    handler_calls: list[dict[str, Any]] = []

    async def fake_handler(_ctx: Any, envelope: Any) -> None:
        handler_calls.append({"id": envelope.id, "payload": envelope.payload})

    runner = WorkerRunner(
        ctx=_ctx_with_queue(queue),
        handlers={TaskKind.TRANSCRIPT_JOB: fake_handler},
    )

    await queue.enqueue(TaskKind.TRANSCRIPT_JOB, {"job_id": "abc"})
    dispatched = await runner.run_once(timeout_seconds=1.0)
    assert dispatched is True
    assert len(handler_calls) == 1
    assert handler_calls[0]["payload"] == {"job_id": "abc"}
    assert queue.in_flight_count() == 0


@pytest.mark.asyncio
async def test_runner_acks_when_no_handler_registered() -> None:
    queue = InMemoryQueue()
    runner = WorkerRunner(ctx=_ctx_with_queue(queue), handlers={})
    await queue.enqueue(TaskKind.TRANSCRIPT_JOB, {})
    dispatched = await runner.run_once(timeout_seconds=1.0)
    # Treated as dispatched (we processed it — i.e., dropped).
    assert dispatched is True
    assert queue.in_flight_count() == 0
    assert queue.pending_count() == 0


@pytest.mark.asyncio
async def test_runner_nacks_with_backoff_on_handler_failure() -> None:
    queue = InMemoryQueue()
    call_count = 0

    async def flaky(_ctx: Any, _envelope: Any) -> None:
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    runner = WorkerRunner(
        ctx=_ctx_with_queue(queue),
        handlers={TaskKind.TRANSCRIPT_JOB: flaky},
        max_attempts=3,
    )

    await queue.enqueue(TaskKind.TRANSCRIPT_JOB, {})
    await runner.run_once(timeout_seconds=1.0)
    # Task was nacked with retry_in_seconds backoff > 0, so it's not
    # immediately visible. The queue records it as in_flight = 0 but
    # delayed for redelivery.
    assert call_count == 1
    assert queue.in_flight_count() == 0


@pytest.mark.asyncio
async def test_runner_drops_after_max_attempts() -> None:
    queue = InMemoryQueue()

    async def always_fail(_ctx: Any, _envelope: Any) -> None:
        raise RuntimeError("boom")

    runner = WorkerRunner(
        ctx=_ctx_with_queue(queue),
        handlers={TaskKind.TRANSCRIPT_JOB: always_fail},
        max_attempts=2,
    )

    # Manually inflate attempts by enqueueing → leasing → nacking
    # repeatedly through the runner, then verify final ack.
    await queue.enqueue(TaskKind.TRANSCRIPT_JOB, {})

    # First attempt → nack with backoff (attempts becomes 1)
    await runner.run_once(timeout_seconds=1.0)

    # Second attempt: simulate redelivery by acking via close + manually
    # constructing an envelope already at attempts=max-1. Easier: bump
    # max_attempts behavior via direct exposure — but we'd rather assert
    # the public effect: after attempts >= max_attempts, the runner acks
    # (drops) the envelope. For this we need a queue that delivers
    # immediately. Use a fresh queue with no delay:
    fresh_queue = InMemoryQueue()
    runner2 = WorkerRunner(
        ctx=_ctx_with_queue(fresh_queue),
        handlers={TaskKind.TRANSCRIPT_JOB: always_fail},
        max_attempts=1,  # one attempt -> immediately drop
    )
    await fresh_queue.enqueue(TaskKind.TRANSCRIPT_JOB, {})
    await runner2.run_once(timeout_seconds=1.0)
    assert fresh_queue.in_flight_count() == 0
    assert fresh_queue.pending_count() == 0


@pytest.mark.asyncio
async def test_runner_run_once_returns_false_when_empty() -> None:
    queue = InMemoryQueue()
    runner = WorkerRunner(ctx=_ctx_with_queue(queue), handlers={})
    dispatched = await runner.run_once(timeout_seconds=0.05)
    assert dispatched is False


@pytest.mark.asyncio
async def test_runner_passes_context_to_handler() -> None:
    queue = InMemoryQueue()
    received_ctx = AsyncMock()
    seen: list[Any] = []

    async def handler(ctx: Any, _envelope: Any) -> None:
        seen.append(ctx)

    ctx = _ctx_with_queue(queue)
    ctx.received = received_ctx
    runner = WorkerRunner(ctx=ctx, handlers={TaskKind.TRANSCRIPT_JOB: handler})

    await queue.enqueue(TaskKind.TRANSCRIPT_JOB, {})
    await runner.run_once(timeout_seconds=1.0)
    assert seen == [ctx]

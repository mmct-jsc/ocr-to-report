"""Phase 7 — InMemoryQueue + Queue Protocol tests."""

from __future__ import annotations

import asyncio

import pytest

from ocr_to_report.adapters.queue import (
    InMemoryQueue,
    Queue,
    QueueClosedError,
    TaskKind,
)


def test_in_memory_queue_satisfies_protocol() -> None:
    q: Queue = InMemoryQueue()
    assert isinstance(q, Queue)


@pytest.mark.asyncio
async def test_enqueue_lease_ack_round_trip() -> None:
    q = InMemoryQueue()
    sent = await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"job_id": "abc"})

    received = await q.lease(timeout_seconds=1.0)
    assert received is not None
    assert received.id == sent.id
    assert received.kind is TaskKind.TRANSCRIPT_JOB
    assert received.payload == {"job_id": "abc"}
    assert received.attempts == 0

    await q.ack(received)
    assert q.in_flight_count() == 0
    assert q.pending_count() == 0


@pytest.mark.asyncio
async def test_lease_returns_none_when_empty() -> None:
    q = InMemoryQueue()
    assert await q.lease(timeout_seconds=0.1) is None


@pytest.mark.asyncio
async def test_lease_blocks_then_returns_when_enqueue_arrives() -> None:
    q = InMemoryQueue()

    async def producer() -> None:
        await asyncio.sleep(0.05)
        await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"job_id": "b"})

    async with asyncio.TaskGroup() as tg:
        tg.create_task(producer())
        envelope = await q.lease(timeout_seconds=2.0)

    assert envelope is not None
    assert envelope.payload["job_id"] == "b"


@pytest.mark.asyncio
async def test_nack_redelivers_with_incremented_attempts() -> None:
    q = InMemoryQueue()
    await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"job_id": "n"})

    first = await q.lease(timeout_seconds=1.0)
    assert first is not None
    assert first.attempts == 0

    await q.nack(first, retry_in_seconds=0.0)

    second = await q.lease(timeout_seconds=1.0)
    assert second is not None
    assert second.id == first.id
    assert second.attempts == 1


@pytest.mark.asyncio
async def test_nack_with_delay_makes_task_invisible_until_due() -> None:
    q = InMemoryQueue()
    await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"x": 1})
    leased = await q.lease(timeout_seconds=1.0)
    assert leased is not None
    await q.nack(leased, retry_in_seconds=0.5)

    # Tight bound — must still be hidden during the delay window.
    assert await q.lease(timeout_seconds=0.05) is None

    # Sleep past the delay so the call_later callback has fired before
    # we lease — avoids race with Windows-coarse timer resolution.
    await asyncio.sleep(0.6)

    redelivered = await q.lease(timeout_seconds=2.0)
    assert redelivered is not None
    assert redelivered.attempts == 1


@pytest.mark.asyncio
async def test_visibility_timeout_redelivers_unacked_task() -> None:
    q = InMemoryQueue(visibility_timeout_seconds=0.1)
    await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"x": 1})

    leased = await q.lease(timeout_seconds=1.0)
    assert leased is not None
    # Don't ack — wait for visibility timeout to lapse.
    await asyncio.sleep(0.2)

    redelivered = await q.lease(timeout_seconds=1.0)
    assert redelivered is not None
    assert redelivered.id == leased.id
    assert redelivered.attempts == 1


@pytest.mark.asyncio
async def test_close_unblocks_pending_lease() -> None:
    q = InMemoryQueue()

    async def closer() -> None:
        await asyncio.sleep(0.05)
        await q.close()

    closer_task = asyncio.create_task(closer())
    with pytest.raises(QueueClosedError):
        await q.lease(timeout_seconds=2.0)
    await closer_task


@pytest.mark.asyncio
async def test_enqueue_after_close_raises() -> None:
    q = InMemoryQueue()
    await q.close()
    with pytest.raises(QueueClosedError):
        await q.enqueue(TaskKind.TRANSCRIPT_JOB, {})


@pytest.mark.asyncio
async def test_fifo_order_preserved() -> None:
    q = InMemoryQueue()
    for i in range(5):
        await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"i": i})
    seen: list[int] = []
    for _ in range(5):
        env = await q.lease(timeout_seconds=1.0)
        assert env is not None
        seen.append(env.payload["i"])
    assert seen == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_delay_seconds_holds_until_due() -> None:
    q = InMemoryQueue()
    await q.enqueue(TaskKind.TRANSCRIPT_JOB, {"k": "delayed"}, delay_seconds=0.5)

    # Hidden during the delay window (tight bound to confirm hidden
    # immediately, not after the delay expired).
    assert await q.lease(timeout_seconds=0.05) is None

    # Sleep past the delay so the call_later callback has fired before
    # we lease — this avoids a race on Windows where timer resolution
    # is coarse.
    await asyncio.sleep(0.6)

    delivered = await q.lease(timeout_seconds=2.0)
    assert delivered is not None
    assert delivered.payload["k"] == "delayed"

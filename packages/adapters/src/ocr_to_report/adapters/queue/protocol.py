"""Async task-queue protocol.

The worker never depends on a concrete queue implementation; it consumes
the :class:`Queue` :class:`Protocol` so tests can run against an
in-memory FIFO and production can run against Redis (Arq), SQS, or
Postgres NOTIFY without touching a line of worker logic.

A :class:`TaskEnvelope` is the unit of work — the queue is intentionally
ignorant of the payload's domain meaning. The worker dispatches by
``kind`` to a registered handler.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class QueueClosedError(RuntimeError):
    """Raised by ``lease()`` after :meth:`Queue.close` has been called.

    The worker treats this as a graceful shutdown signal — it stops
    polling and exits its run loop without logging an error.
    """


class TaskKind(StrEnum):
    """Stable identifiers used to dispatch envelopes to handlers."""

    TRANSCRIPT_JOB = "transcript_job"
    """Run the full extract+render pipeline for a single ``Job`` row."""

    BATCH_SUBMIT = "batch_submit"
    """Bundle a set of pending jobs into one Anthropic Batch API request."""

    BATCH_POLL = "batch_poll"
    """Poll an in-flight batch; on completion, fan results back into jobs."""

    RETENTION_SWEEP = "retention_sweep"
    """Periodic: purge jobs whose ``expires_at`` is in the past."""


@dataclass(frozen=True, slots=True)
class TaskEnvelope:
    """A queued unit of work.

    Attributes:
        id: Unique task id; used for idempotent ack/nack.
        kind: Discriminator the worker dispatches on. See :class:`TaskKind`.
        payload: Arbitrary JSON-serializable dict. Handlers know the
            expected shape per ``kind``.
        attempts: Times this task has been delivered. Starts at 0 and
            increments on every redelivery (after a nack or lease
            timeout).
        enqueued_at: Wall-clock time the task was first put on the queue.
            Useful for queue-age metrics and starvation detection.
        tenant_id: Optional tenant scope. Not enforced at the queue layer
            — it's metadata for handlers + observability.
    """

    id: uuid.UUID
    kind: TaskKind
    payload: dict[str, Any]
    attempts: int = 0
    enqueued_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    tenant_id: uuid.UUID | None = None


@runtime_checkable
class Queue(Protocol):
    """A pluggable async work queue.

    Implementations MUST be safe to share across concurrent producers
    and consumers (asyncio-safe). They MUST also provide *at-least-once*
    delivery: a leased task that is neither acked nor nacked within
    ``visibility_timeout`` is redelivered with ``attempts`` incremented.
    """

    async def enqueue(
        self,
        kind: TaskKind,
        payload: dict[str, Any],
        *,
        tenant_id: uuid.UUID | None = None,
        delay_seconds: float = 0.0,
    ) -> TaskEnvelope:
        """Place a new task on the queue.

        Args:
            kind: Handler discriminator.
            payload: JSON-serializable handler input.
            tenant_id: Optional tenant scope for metrics + tracing.
            delay_seconds: If >0, the task only becomes leasable after
                this many seconds. Use for retry-with-backoff.

        Returns:
            The enqueued :class:`TaskEnvelope`.
        """
        ...

    async def lease(self, *, timeout_seconds: float = 5.0) -> TaskEnvelope | None:
        """Block up to ``timeout_seconds`` for the next available task.

        Returns ``None`` if the wait elapses with no task available.
        Raises :class:`QueueClosedError` if the queue was closed while
        waiting.
        """
        ...

    async def ack(self, envelope: TaskEnvelope) -> None:
        """Mark the task as completed; remove it permanently.

        Idempotent: acking an unknown id is a no-op.
        """
        ...

    async def nack(
        self,
        envelope: TaskEnvelope,
        *,
        retry_in_seconds: float = 0.0,
    ) -> None:
        """Mark the task as failed; redeliver with ``attempts``+1.

        Args:
            envelope: The task that failed.
            retry_in_seconds: Delay before the task becomes leasable
                again. The handler chooses the backoff curve.
        """
        ...

    async def close(self) -> None:
        """Stop accepting new work + signal pending lessees to exit.

        Idempotent. After ``close``, ``lease`` raises
        :class:`QueueClosedError`. Pending tasks may still be inspected
        by the implementation for diagnostics but will not be redelivered.
        """
        ...


__all__ = [
    "Queue",
    "QueueClosedError",
    "TaskEnvelope",
    "TaskKind",
]

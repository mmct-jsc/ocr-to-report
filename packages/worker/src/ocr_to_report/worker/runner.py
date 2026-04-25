"""Worker dispatch loop.

The runner pulls envelopes off the queue, dispatches each by ``kind`` to
the registered handler, and acks/nacks based on the outcome. Failed
handlers are retried with exponential backoff up to ``max_attempts``;
beyond that the envelope is dropped with a structured log line.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ocr_to_report.adapters.queue import QueueClosedError, TaskEnvelope, TaskKind
from ocr_to_report.worker.context import WorkerContext
from ocr_to_report.worker.handlers import (
    handle_batch_poll,
    handle_batch_submit,
    handle_retention_sweep,
    handle_transcript_job,
)

_LOG = logging.getLogger("ocr_to_report.worker")

Handler = Callable[[WorkerContext, TaskEnvelope], Awaitable[None]]


def _default_handlers() -> dict[TaskKind, Handler]:
    return {
        TaskKind.TRANSCRIPT_JOB: handle_transcript_job,
        TaskKind.BATCH_SUBMIT: handle_batch_submit,
        TaskKind.BATCH_POLL: handle_batch_poll,
        TaskKind.RETENTION_SWEEP: handle_retention_sweep,
    }


@dataclass(slots=True)
class WorkerRunner:
    """Pull-and-dispatch loop.

    Args:
        ctx: Long-lived worker context (queue, db, vision, etc.).
        handlers: Per-:class:`TaskKind` async handlers. Defaults to the
            full built-in set; tests inject a partial map.
        max_attempts: Tasks delivered more than this many times are
            dropped (and a warning logged). Counts the original delivery,
            so a value of ``5`` means up to 4 retries.
        lease_timeout_seconds: How long :meth:`run` waits for the next
            envelope before re-checking shutdown state.
    """

    ctx: WorkerContext
    handlers: dict[TaskKind, Handler] | None = None
    max_attempts: int = 5
    lease_timeout_seconds: float = 5.0
    _shutdown_event: asyncio.Event | None = None

    def __post_init__(self) -> None:
        if self.handlers is None:
            self.handlers = _default_handlers()
        self._shutdown_event = asyncio.Event()

    async def run(self) -> None:
        """Main loop. Returns when :meth:`stop` is called or the queue closes."""
        assert self._shutdown_event is not None
        while not self._shutdown_event.is_set():
            try:
                envelope = await self.ctx.queue.lease(
                    timeout_seconds=self.lease_timeout_seconds,
                )
            except QueueClosedError:
                return
            if envelope is None:
                continue
            await self._process(envelope)

    async def stop(self) -> None:
        """Request a graceful shutdown after the in-flight handler finishes."""
        if self._shutdown_event is not None:
            self._shutdown_event.set()

    async def run_once(self, *, timeout_seconds: float = 5.0) -> bool:
        """Process at most one envelope (test convenience). Returns True
        if a task was dispatched, False if the wait elapsed."""
        try:
            envelope = await self.ctx.queue.lease(timeout_seconds=timeout_seconds)
        except QueueClosedError:
            return False
        if envelope is None:
            return False
        await self._process(envelope)
        return True

    async def _process(self, envelope: TaskEnvelope) -> None:
        handlers = self.handlers
        assert handlers is not None
        handler = handlers.get(envelope.kind)
        if handler is None:
            _LOG.warning(
                "no handler registered for task kind",
                extra={"task_kind": envelope.kind.value, "task_id": str(envelope.id)},
            )
            await self.ctx.queue.ack(envelope)
            return
        try:
            await handler(self.ctx, envelope)
        except Exception as exc:
            attempts_so_far = envelope.attempts + 1
            if attempts_so_far >= self.max_attempts:
                _LOG.error(
                    "task exhausted retries; dropping",
                    extra={
                        "task_kind": envelope.kind.value,
                        "task_id": str(envelope.id),
                        "attempts": attempts_so_far,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )
                await self.ctx.queue.ack(envelope)
                return
            backoff = _retry_backoff(attempts_so_far)
            _LOG.warning(
                "task failed; nacking with backoff",
                extra={
                    "task_kind": envelope.kind.value,
                    "task_id": str(envelope.id),
                    "attempts": attempts_so_far,
                    "retry_in_seconds": backoff,
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            await self.ctx.queue.nack(envelope, retry_in_seconds=backoff)
            return
        await self.ctx.queue.ack(envelope)


def _retry_backoff(attempts_so_far: int) -> float:
    """Exponential backoff with a 5-minute ceiling.

    attempts_so_far=1 → 2s, =2 → 4s, =3 → 8s, =4 → 16s, …, capped at 300.
    """
    return min(2.0**attempts_so_far, 300.0)


__all__ = ["Handler", "WorkerRunner"]

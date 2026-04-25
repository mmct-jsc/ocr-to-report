"""Single-process FIFO queue with visibility-timeout semantics.

Used by tests + ``make dev`` (no Redis required). Production deployments
swap in a Redis or SQS implementation that conforms to the same
:class:`Queue` Protocol — the worker never sees the difference.

Behavior:

* ``enqueue`` appends to a deque; ``delay_seconds`` schedules the task
  via a ``visible_at`` timestamp.
* ``lease`` pops the oldest visible task. If a leased task is not
  acked/nacked within ``visibility_timeout`` it becomes visible again
  with ``attempts`` incremented.
* ``ack`` removes the task from the leased map; ``nack`` re-enqueues
  with backoff.
* The implementation is fully asyncio-native (asyncio.Lock + Event +
  loop.call_at for delayed visibility) — no threads.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from ocr_to_report.adapters.queue.protocol import (
    QueueClosedError,
    TaskEnvelope,
    TaskKind,
)


class InMemoryQueue:
    """Asyncio-native, single-process queue.

    Args:
        visibility_timeout_seconds: How long a leased task remains hidden
            from other consumers before it becomes leasable again. The
            worker should ack/nack well before this elapses.
    """

    def __init__(self, *, visibility_timeout_seconds: float = 60.0) -> None:
        self._ready: deque[TaskEnvelope] = deque()
        """Tasks that are visible right now, ordered by enqueue time."""
        self._delayed: list[tuple[float, TaskEnvelope]] = []
        """(visible_at_monotonic, task) pairs not yet promoted to ``_ready``."""
        self._leased: dict[uuid.UUID, _LeaseRecord] = {}
        """In-flight tasks keyed by id; lease record carries the timer handle."""

        self._lock = asyncio.Lock()
        self._has_work = asyncio.Event()
        self._closed = False
        self._visibility_timeout = visibility_timeout_seconds

    async def enqueue(
        self,
        kind: TaskKind,
        payload: dict[str, Any],
        *,
        tenant_id: uuid.UUID | None = None,
        delay_seconds: float = 0.0,
    ) -> TaskEnvelope:
        if self._closed:
            raise QueueClosedError("queue is closed; cannot enqueue")
        envelope = TaskEnvelope(
            id=uuid.uuid4(),
            kind=kind,
            payload=dict(payload),
            attempts=0,
            enqueued_at=datetime.now(tz=UTC),
            tenant_id=tenant_id,
        )
        async with self._lock:
            self._schedule_visible(envelope, delay_seconds)
        return envelope

    async def lease(self, *, timeout_seconds: float = 5.0) -> TaskEnvelope | None:
        deadline = asyncio.get_event_loop().time() + timeout_seconds
        while True:
            if self._closed:
                raise QueueClosedError("queue closed during lease()")
            async with self._lock:
                self._promote_due_delayed()
                if self._ready:
                    envelope = self._ready.popleft()
                    self._record_lease(envelope)
                    if not self._ready:
                        self._has_work.clear()
                    return envelope
                self._has_work.clear()
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                return None
            try:
                await asyncio.wait_for(self._has_work.wait(), timeout=remaining)
            except TimeoutError:
                return None

    async def ack(self, envelope: TaskEnvelope) -> None:
        async with self._lock:
            record = self._leased.pop(envelope.id, None)
            if record is not None:
                record.cancel()

    async def nack(
        self,
        envelope: TaskEnvelope,
        *,
        retry_in_seconds: float = 0.0,
    ) -> None:
        async with self._lock:
            record = self._leased.pop(envelope.id, None)
            if record is not None:
                record.cancel()
            redelivered = replace(envelope, attempts=envelope.attempts + 1)
            self._schedule_visible(redelivered, retry_in_seconds)

    async def close(self) -> None:
        self._closed = True
        async with self._lock:
            for record in self._leased.values():
                record.cancel()
            self._leased.clear()
            self._ready.clear()
            self._delayed.clear()
        self._has_work.set()  # release any pending lease() callers

    # ─── Inspection helpers (tests + observability) ──────────
    def pending_count(self) -> int:
        """Approximate visible-queue depth. Not synchronized — best-effort."""
        return len(self._ready)

    def in_flight_count(self) -> int:
        """Number of tasks currently leased (not yet acked/nacked)."""
        return len(self._leased)

    # ─── Internals ────────────────────────────────────────────
    def _schedule_visible(self, envelope: TaskEnvelope, delay_seconds: float) -> None:
        """Place ``envelope`` on either the ready deque or the delayed list."""
        if delay_seconds <= 0.0:
            self._ready.append(envelope)
            self._has_work.set()
            return
        loop = asyncio.get_event_loop()
        visible_at = loop.time() + delay_seconds
        self._delayed.append((visible_at, envelope))
        loop.call_later(delay_seconds, self._promote_callback)

    def _promote_callback(self) -> None:
        """Wakeup hook called by ``loop.call_later`` when a delay elapses."""
        self._promote_due_delayed()
        if self._ready:
            self._has_work.set()

    def _promote_due_delayed(self) -> None:
        """Move any delayed tasks whose ``visible_at`` has passed into ready."""
        if not self._delayed:
            return
        now = asyncio.get_event_loop().time()
        still_delayed: list[tuple[float, TaskEnvelope]] = []
        for visible_at, envelope in self._delayed:
            if visible_at <= now:
                self._ready.append(envelope)
            else:
                still_delayed.append((visible_at, envelope))
        self._delayed = still_delayed

    def _record_lease(self, envelope: TaskEnvelope) -> None:
        """Record a lease and arm the visibility-timeout reclaimer."""
        loop = asyncio.get_event_loop()
        timer = loop.call_later(
            self._visibility_timeout,
            self._reclaim_callback,
            envelope.id,
        )
        self._leased[envelope.id] = _LeaseRecord(
            envelope=envelope,
            leased_at=datetime.now(tz=UTC),
            timer=timer,
        )

    def _reclaim_callback(self, task_id: uuid.UUID) -> None:
        """Reclaim a task whose lease expired without ack/nack."""
        record = self._leased.pop(task_id, None)
        if record is None:
            return
        redelivered = replace(record.envelope, attempts=record.envelope.attempts + 1)
        self._ready.append(redelivered)
        self._has_work.set()


class _LeaseRecord:
    """Internal: a leased task plus the timer that would reclaim it."""

    __slots__ = ("envelope", "leased_at", "timer")

    def __init__(
        self,
        *,
        envelope: TaskEnvelope,
        leased_at: datetime,
        timer: object,
    ) -> None:
        self.envelope = envelope
        self.leased_at = leased_at
        self.timer = timer

    def cancel(self) -> None:
        # asyncio.TimerHandle has .cancel(); use duck-typing to avoid
        # importing the concrete type for a structural attribute.
        cancel: Any = getattr(self.timer, "cancel", None)
        if cancel is not None:
            cancel()


__all__ = ["InMemoryQueue"]

"""Async task queue layer.

Public surface:

* :class:`Queue` — Protocol every queue implementation conforms to.
* :class:`TaskEnvelope` — typed wrapper around an enqueued unit of work.
* :class:`InMemoryQueue` — single-process FIFO with visibility-timeout
  semantics, used by tests + dev. Production deployments swap in a Redis-
  or SQS-backed implementation behind the same Protocol — none of the
  worker code changes.
* :class:`QueueClosedError` — raised by ``lease`` after :meth:`Queue.close`.
"""

from ocr_to_report.adapters.queue.in_memory import InMemoryQueue
from ocr_to_report.adapters.queue.protocol import (
    Queue,
    QueueClosedError,
    TaskEnvelope,
    TaskKind,
)

__all__ = [
    "InMemoryQueue",
    "Queue",
    "QueueClosedError",
    "TaskEnvelope",
    "TaskKind",
]

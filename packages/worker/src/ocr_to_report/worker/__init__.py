"""OCR-to-Report async worker.

Public surface:

* :class:`WorkerContext` — shared services injected into every handler
  (db sessionmaker, queue, blob store, vision adapters, encryptor, etc.).
* :class:`WorkerRunner` — the dispatch loop. Pulls envelopes off the
  queue, looks up the handler for ``kind``, dispatches.
* :func:`build_worker_context` — assemble a :class:`WorkerContext` from
  app settings.
* Handler functions for each :class:`TaskKind`:
    * :func:`handle_transcript_job`
    * :func:`handle_batch_submit`
    * :func:`handle_batch_poll`
    * :func:`handle_retention_sweep`
* :class:`RetentionService` — extracted purge logic, callable from cron
  outside the worker.

The worker process is started via ``python -m ocr_to_report.worker`` or
``ocr-to-report-worker`` (entry-point in ``pyproject.toml``).
"""

from ocr_to_report.worker.context import WorkerContext, build_worker_context
from ocr_to_report.worker.handlers import (
    handle_batch_poll,
    handle_batch_submit,
    handle_retention_sweep,
    handle_transcript_job,
)
from ocr_to_report.worker.retention import RetentionService
from ocr_to_report.worker.runner import WorkerRunner

__all__ = [
    "RetentionService",
    "WorkerContext",
    "WorkerRunner",
    "build_worker_context",
    "handle_batch_poll",
    "handle_batch_submit",
    "handle_retention_sweep",
    "handle_transcript_job",
]
__version__ = "0.1.0-dev"

"""``python -m ocr_to_report.worker`` entrypoint.

Boots the worker process: loads :class:`Settings`, builds a
:class:`WorkerContext`, and runs :class:`WorkerRunner` until SIGINT /
SIGTERM. Logging is set up via the ``OCR2R_LOG_LEVEL`` env var.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

from ocr_to_report.api.settings import load_settings
from ocr_to_report.worker.context import build_worker_context
from ocr_to_report.worker.runner import WorkerRunner


async def _amain() -> int:
    settings = load_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level, logging.INFO))
    log = logging.getLogger("ocr_to_report.worker")

    ctx = build_worker_context(settings)
    runner = WorkerRunner(ctx=ctx)

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _request_stop(signame: str) -> None:
        log.info("received %s; draining worker", signame)
        stop_event.set()

    if sys.platform != "win32":
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, _request_stop, sig.name)

    runner_task = asyncio.create_task(runner.run())
    await stop_event.wait()
    await runner.stop()
    await runner_task
    return 0


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    main()

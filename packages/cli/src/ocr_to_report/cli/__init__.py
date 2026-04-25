"""OCR-to-Report Typer CLI.

Wraps :mod:`ocr_to_report.sdk_py` so the CLI and the SDK share the
same on-the-wire contract — there is no second client implementation
to keep in sync.

Top-level commands:

* ``ocr-to-report process``  — POST /v1/transcripts on a single file.
* ``ocr-to-report batch``    — POST /v1/transcripts:batch on a list.
* ``ocr-to-report jobs``     — get / list / approve / reject / fetch.
* ``ocr-to-report templates``— list available targets.
* ``ocr-to-report usage``    — current-period rollup.
* ``ocr-to-report webhooks`` — create / list.

Auth defaults to ``OCR2R_API_KEY`` env var; ``--api-key`` overrides.
Server URL defaults to ``OCR2R_BASE_URL`` (or ``http://localhost:8000``);
``--base-url`` overrides.
"""

from ocr_to_report.cli.app import app

__all__ = ["app"]
__version__ = "0.1.0-dev"

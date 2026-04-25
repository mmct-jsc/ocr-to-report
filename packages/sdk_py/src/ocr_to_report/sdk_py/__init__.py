"""OCR-to-Report public Python SDK.

HTTP client for the REST API plus an opt-in re-export of the core domain
library for in-process use. Never imports server-side code (api / adapters /
worker) — enforced by import-linter.
"""

__all__: list[str] = []
__version__ = "0.1.0-dev"

"""OCR-to-Report core domain library.

Pure-domain types, profile/target schemas, mapping engine (Phase 2+),
pipeline engine (Phase 4+). No I/O dependencies. Imported by every other
package.

Public API surface (re-exported here for convenience; submodules remain
the source of truth for stability guarantees):

* :mod:`ocr_to_report.core.canonical` — universal IR
* :mod:`ocr_to_report.core.profile` — source profile schemas
* :mod:`ocr_to_report.core.target` — target system schemas
* :mod:`ocr_to_report.core.enums` — fixed vocabularies
* :mod:`ocr_to_report.core.errors` — exception hierarchy + RFC 7807
* :mod:`ocr_to_report.core.pii` — PII classification + redaction
* :mod:`ocr_to_report.core.types` — shared utility types
"""

__all__: list[str] = []
__version__ = "0.1.0-dev"

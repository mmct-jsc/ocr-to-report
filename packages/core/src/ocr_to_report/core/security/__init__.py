"""Input-hardening primitives.

* :func:`detect_media_type` — magic-byte sniffing for PDF/PNG/JPEG/etc.
* :func:`require_safe_upload` — combines size + magic-byte check; raises
  :class:`UnsupportedMediaTypeError` or :class:`PayloadTooLargeError`.
"""

from ocr_to_report.core.security.uploads import (
    SUPPORTED_MEDIA_TYPES,
    detect_media_type,
    require_safe_upload,
)

__all__ = [
    "SUPPORTED_MEDIA_TYPES",
    "detect_media_type",
    "require_safe_upload",
]

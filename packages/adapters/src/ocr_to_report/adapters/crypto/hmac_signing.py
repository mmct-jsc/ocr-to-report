"""HMAC-SHA256 signing for webhook payloads.

Stripe-style header: ``X-OCR-Signature: t=<unix>,v1=<hex>``. Verifier
checks both the timestamp (replay window) and the constant-time MAC.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from typing import Final

from ocr_to_report.core.errors.domain import OcrToReportError

DEFAULT_REPLAY_WINDOW_SECONDS: Final[int] = 300


class HmacError(OcrToReportError):
    """HMAC signature missing, malformed, or invalid."""

    status = 401
    type_uri = "https://errors.ocr-to-report/hmac"
    title = "HMAC verification failed"


def hmac_sign(payload: bytes, secret: bytes, *, timestamp: int | None = None) -> str:
    """Produce a header value of the form ``t=<unix>,v1=<hex_mac>``."""
    ts = timestamp if timestamp is not None else int(time.time())
    signed = f"{ts}.".encode() + payload
    mac = hmac.new(secret, signed, hashlib.sha256).hexdigest()
    return f"t={ts},v1={mac}"


def hmac_verify(
    payload: bytes,
    header: str,
    secret: bytes,
    *,
    replay_window_seconds: int = DEFAULT_REPLAY_WINDOW_SECONDS,
    now: int | None = None,
) -> None:
    """Verify the header's signature; raise :class:`HmacError` if invalid.

    Always uses constant-time comparison.
    """
    parts = dict(p.split("=", 1) for p in header.split(",") if "=" in p)
    if "t" not in parts or "v1" not in parts:
        raise HmacError("signature header missing 't' or 'v1' component")
    try:
        ts = int(parts["t"])
    except ValueError as e:
        raise HmacError("signature timestamp is not an integer") from e

    if replay_window_seconds > 0:
        cur = now if now is not None else int(time.time())
        if abs(cur - ts) > replay_window_seconds:
            raise HmacError(
                f"signature timestamp {ts} outside replay window ({replay_window_seconds}s)",
            )

    expected = hmac.new(secret, f"{ts}.".encode() + payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts["v1"]):
        raise HmacError("signature does not match payload")


__all__ = ["DEFAULT_REPLAY_WINDOW_SECONDS", "HmacError", "hmac_sign", "hmac_verify"]

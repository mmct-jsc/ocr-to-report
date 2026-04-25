"""API-key generation, hashing (Argon2id), and verification.

Tenant-facing API keys look like::

    sk_live_<22-byte-base32>      # production
    sk_test_<22-byte-base32>      # staging / testing

Only the **first 8 characters** of an API key are stored in plaintext in
the database (for dashboard display). The full key is hashed with
Argon2id; the hash is what's compared at auth time.
"""

from __future__ import annotations

import base64
import re
import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from ocr_to_report.core.errors.domain import OcrToReportError

API_KEY_LIVE_PREFIX: Final[str] = "sk_live_"
API_KEY_TEST_PREFIX: Final[str] = "sk_test_"
_PREFIX_DISPLAY_CHARS: Final[int] = 8

# 22 base32 chars = 110 bits of entropy.
_KEY_BODY_BYTES: Final[int] = 14  # 14 bytes = 112 bits, encoded to 23 base32 chars
_KEY_BODY_LEN: Final[int] = 23

_KEY_RE: Final = re.compile(
    rf"^(?:{re.escape(API_KEY_LIVE_PREFIX)}|{re.escape(API_KEY_TEST_PREFIX)})[A-Za-z0-9]{{20,40}}$"
)


class ApiKeyError(OcrToReportError):
    """API key validation / hashing failure."""

    status = 500
    type_uri = "https://errors.ocr-to-report/api-key"
    title = "API key error"


# Argon2id parameters: 64 MiB memory, 3 iterations, 4 parallelism.
# Tuned for ~50ms on commodity server hardware. Adjust for your tier.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,
    parallelism=4,
)


def generate_api_key(*, live: bool = False) -> str:
    """Generate a fresh API key with the appropriate prefix."""
    body = base64.b32encode(secrets.token_bytes(_KEY_BODY_BYTES)).decode("ascii")
    body = body.rstrip("=")
    prefix = API_KEY_LIVE_PREFIX if live else API_KEY_TEST_PREFIX
    return f"{prefix}{body}"


def api_key_prefix(api_key: str) -> str:
    """Return the dashboard-displayable prefix.

    Always 8 characters: ``sk_live_`` / ``sk_test_`` (which are 8 chars
    each by design — 'sk_live_' is 8 chars including the trailing
    underscore).
    """
    if len(api_key) < _PREFIX_DISPLAY_CHARS:
        raise ApiKeyError("api_key is too short to derive a prefix")
    return api_key[:_PREFIX_DISPLAY_CHARS]


def hash_api_key(api_key: str) -> str:
    """Argon2id-hash an API key; returns the encoded hash string."""
    if not _KEY_RE.match(api_key):
        raise ApiKeyError("api_key does not match expected shape")
    return _HASHER.hash(api_key)


def verify_api_key(api_key: str, hashed: str) -> bool:
    """Verify a key against its stored Argon2id hash. Returns True iff valid."""
    try:
        return _HASHER.verify(hashed, api_key)
    except VerifyMismatchError:
        return False
    except Exception as e:
        raise ApiKeyError(f"verify failed: {e}") from e


__all__ = [
    "API_KEY_LIVE_PREFIX",
    "API_KEY_TEST_PREFIX",
    "ApiKeyError",
    "api_key_prefix",
    "generate_api_key",
    "hash_api_key",
    "verify_api_key",
]

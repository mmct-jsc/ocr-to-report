"""Envelope encryption: per-tenant DEKs wrapped by a master KEK.

Pattern:

* Each tenant has its own 32-byte Data Encryption Key (DEK).
* The DEK never appears in plaintext on disk — it is encrypted by the
  Key Encryption Key (KEK) and stored in the tenants table as
  ``dek_wrapped`` bytes.
* The KEK comes from a :class:`KEKProvider` — env in MVP, KMS/HSM later.
* Per-row PII columns are AES-GCM-256 encrypted with the unwrapped DEK.

Crypto-shredding on tenant deletion: destroying the wrapped DEK makes
every encrypted row for that tenant irrecoverable.
"""

from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from typing import Final, Protocol, runtime_checkable

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ocr_to_report.core.errors.domain import OcrToReportError

DEK_BYTES: Final[int] = 32
"""AES-256-GCM key size."""

NONCE_BYTES: Final[int] = 12
"""GCM nonce size (96 bits is the standard NIST recommendation)."""


class CryptoError(OcrToReportError):
    """Encryption / decryption failure (or KEK access failure)."""

    status = 500
    type_uri = "https://errors.ocr-to-report/crypto"
    title = "Cryptographic operation failed"


@runtime_checkable
class KEKProvider(Protocol):
    """Where the master Key Encryption Key comes from.

    Implementations: :class:`EnvKEKProvider` (MVP), KMS/HSM (post-MVP).
    """

    def kek(self) -> bytes: ...


@dataclass(frozen=True, slots=True)
class EnvKEKProvider:
    """Read the KEK from an environment variable, base64-decoded.

    Generate one with::

        python -c "import secrets,base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"
    """

    env_var: str = "OCR2R_KEK_B64"

    def kek(self) -> bytes:
        raw = os.environ.get(self.env_var)
        if not raw:
            raise CryptoError(
                f"environment variable {self.env_var!r} not set; "
                "cannot perform envelope encryption",
                env_var=self.env_var,
            )
        try:
            key = base64.b64decode(raw)
        except (ValueError, TypeError) as e:
            raise CryptoError(
                f"environment variable {self.env_var!r} is not valid base64",
            ) from e
        if len(key) != DEK_BYTES:
            raise CryptoError(
                f"KEK from {self.env_var!r} must be {DEK_BYTES} bytes, got {len(key)}",
                expected=DEK_BYTES,
                actual=len(key),
            )
        return key


def generate_dek() -> bytes:
    """Return a fresh random 32-byte DEK."""
    return secrets.token_bytes(DEK_BYTES)


@dataclass(frozen=True, slots=True)
class EncryptedPayload:
    """Wire format for an encrypted column.

    Stored as a single bytes blob: ``nonce || ciphertext_with_tag``.
    """

    nonce: bytes
    ciphertext: bytes  # includes the 16-byte GCM tag at the end

    def to_bytes(self) -> bytes:
        return self.nonce + self.ciphertext

    @classmethod
    def from_bytes(cls, blob: bytes) -> EncryptedPayload:
        if len(blob) < NONCE_BYTES + 16:
            raise CryptoError(
                f"encrypted payload too short: {len(blob)} bytes",
                length=len(blob),
            )
        return cls(nonce=blob[:NONCE_BYTES], ciphertext=blob[NONCE_BYTES:])


def encrypt_payload(
    plaintext: bytes,
    key: bytes,
    *,
    associated_data: bytes | None = None,
) -> EncryptedPayload:
    """AES-GCM encrypt with a random 96-bit nonce.

    ``associated_data`` (optional) is authenticated but not encrypted —
    use it for tenant_id / row_id to bind ciphertext to its row so a
    cross-row substitution attack can't succeed.
    """
    if len(key) != DEK_BYTES:
        raise CryptoError(f"key must be {DEK_BYTES} bytes, got {len(key)}")
    nonce = secrets.token_bytes(NONCE_BYTES)
    try:
        ciphertext = AESGCM(key).encrypt(nonce, plaintext, associated_data)
    except Exception as e:
        raise CryptoError(f"encryption failed: {e}") from e
    return EncryptedPayload(nonce=nonce, ciphertext=ciphertext)


def decrypt_payload(
    payload: EncryptedPayload,
    key: bytes,
    *,
    associated_data: bytes | None = None,
) -> bytes:
    """AES-GCM decrypt; raises :class:`CryptoError` on auth failure."""
    if len(key) != DEK_BYTES:
        raise CryptoError(f"key must be {DEK_BYTES} bytes, got {len(key)}")
    try:
        return AESGCM(key).decrypt(payload.nonce, payload.ciphertext, associated_data)
    except Exception as e:
        raise CryptoError(f"decryption failed: {e}") from e


class EnvelopeEncryptor:
    """High-level wrapper around envelope encryption.

    Holds a :class:`KEKProvider`; provides:

    * :meth:`new_tenant_dek_wrapped` — generate a fresh DEK and return it
      wrapped (for storing in the tenants table).
    * :meth:`unwrap` / :meth:`wrap` — DEK ↔ wrapped DEK round-trip.
    * :meth:`encrypt` / :meth:`decrypt` — column-level operations.

    Stateless aside from the KEK provider; safe to share.
    """

    def __init__(self, kek_provider: KEKProvider) -> None:
        self._kek_provider = kek_provider

    def new_tenant_dek_wrapped(self) -> tuple[bytes, bytes]:
        """Return (dek_plain, dek_wrapped). Caller stores the wrapped form
        and discards the plaintext after use."""
        dek = generate_dek()
        wrapped = self.wrap(dek)
        return dek, wrapped

    def wrap(self, dek: bytes) -> bytes:
        kek = self._kek_provider.kek()
        return encrypt_payload(dek, kek).to_bytes()

    def unwrap(self, dek_wrapped: bytes) -> bytes:
        kek = self._kek_provider.kek()
        payload = EncryptedPayload.from_bytes(dek_wrapped)
        return decrypt_payload(payload, kek)

    def encrypt(
        self,
        plaintext: bytes,
        dek: bytes,
        *,
        associated_data: bytes | None = None,
    ) -> bytes:
        """Encrypt a column value with the tenant's DEK; returns wire bytes."""
        return encrypt_payload(plaintext, dek, associated_data=associated_data).to_bytes()

    def decrypt(
        self,
        wire: bytes,
        dek: bytes,
        *,
        associated_data: bytes | None = None,
    ) -> bytes:
        return decrypt_payload(
            EncryptedPayload.from_bytes(wire),
            dek,
            associated_data=associated_data,
        )


__all__ = [
    "DEK_BYTES",
    "CryptoError",
    "EncryptedPayload",
    "EnvKEKProvider",
    "EnvelopeEncryptor",
    "KEKProvider",
    "decrypt_payload",
    "encrypt_payload",
    "generate_dek",
]

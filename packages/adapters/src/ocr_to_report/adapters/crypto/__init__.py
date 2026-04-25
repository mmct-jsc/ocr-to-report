"""Cryptography primitives.

Public surface:

* :class:`EnvelopeEncryptor` — per-tenant DEK envelope encryption with a
  master KEK from env (or any pluggable :class:`KEKProvider`). AES-GCM-256.
* :func:`hash_api_key` / :func:`verify_api_key` — Argon2id for API keys.
* :func:`generate_api_key` / :func:`api_key_prefix` — issuance helpers.
* :func:`hmac_sign` / :func:`hmac_verify` — webhook payload signing.
"""

from ocr_to_report.adapters.crypto.api_keys import (
    API_KEY_LIVE_PREFIX,
    API_KEY_TEST_PREFIX,
    api_key_prefix,
    generate_api_key,
    hash_api_key,
    verify_api_key,
)
from ocr_to_report.adapters.crypto.envelope import (
    DEK_BYTES,
    EncryptedPayload,
    EnvelopeEncryptor,
    EnvKEKProvider,
    KEKProvider,
    decrypt_payload,
    encrypt_payload,
    generate_dek,
)
from ocr_to_report.adapters.crypto.hmac_signing import hmac_sign, hmac_verify

__all__ = [
    "API_KEY_LIVE_PREFIX",
    "API_KEY_TEST_PREFIX",
    "DEK_BYTES",
    "EncryptedPayload",
    "EnvKEKProvider",
    "EnvelopeEncryptor",
    "KEKProvider",
    "api_key_prefix",
    "decrypt_payload",
    "encrypt_payload",
    "generate_api_key",
    "generate_dek",
    "hash_api_key",
    "hmac_sign",
    "hmac_verify",
    "verify_api_key",
]

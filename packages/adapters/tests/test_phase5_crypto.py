"""Crypto module tests."""

from __future__ import annotations

import base64
import secrets
import time

import pytest

from ocr_to_report.adapters.crypto import (
    DEK_BYTES,
    EncryptedPayload,
    EnvelopeEncryptor,
    EnvKEKProvider,
    api_key_prefix,
    decrypt_payload,
    encrypt_payload,
    generate_api_key,
    generate_dek,
    hash_api_key,
    hmac_sign,
    hmac_verify,
    verify_api_key,
)
from ocr_to_report.adapters.crypto.envelope import CryptoError
from ocr_to_report.adapters.crypto.hmac_signing import HmacError


# ─── Envelope encryption ──────────────────────────────────────
def test_encrypt_decrypt_round_trip() -> None:
    key = generate_dek()
    pt = b"the quick brown fox"
    payload = encrypt_payload(pt, key)
    assert decrypt_payload(payload, key) == pt


def test_encrypt_associated_data_binding() -> None:
    key = generate_dek()
    payload = encrypt_payload(b"secret", key, associated_data=b"tenant=abc")
    # Right AAD passes
    assert decrypt_payload(payload, key, associated_data=b"tenant=abc") == b"secret"
    # Wrong AAD fails authentication
    with pytest.raises(CryptoError):
        decrypt_payload(payload, key, associated_data=b"tenant=xyz")


def test_encrypted_payload_serialization() -> None:
    key = generate_dek()
    payload = encrypt_payload(b"data", key)
    blob = payload.to_bytes()
    restored = EncryptedPayload.from_bytes(blob)
    assert restored.nonce == payload.nonce
    assert restored.ciphertext == payload.ciphertext


def test_encrypt_rejects_wrong_key_size() -> None:
    with pytest.raises(CryptoError):
        encrypt_payload(b"data", b"too short")


def test_encrypted_payload_rejects_truncated() -> None:
    with pytest.raises(CryptoError):
        EncryptedPayload.from_bytes(b"short")


def test_kek_provider_env_var(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = secrets.token_bytes(DEK_BYTES)
    monkeypatch.setenv("OCR2R_KEK_B64", base64.b64encode(kek).decode())
    provider = EnvKEKProvider()
    assert provider.kek() == kek


def test_kek_provider_missing_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCR2R_KEK_B64", raising=False)
    with pytest.raises(CryptoError):
        EnvKEKProvider().kek()


def test_kek_provider_wrong_size(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCR2R_KEK_B64", base64.b64encode(b"too short").decode())
    with pytest.raises(CryptoError):
        EnvKEKProvider().kek()


def test_envelope_encryptor_full_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = secrets.token_bytes(DEK_BYTES)
    monkeypatch.setenv("OCR2R_KEK_B64", base64.b64encode(kek).decode())
    enc = EnvelopeEncryptor(EnvKEKProvider())

    dek_plain, dek_wrapped = enc.new_tenant_dek_wrapped()
    assert len(dek_plain) == DEK_BYTES
    assert dek_wrapped != dek_plain

    # Round-trip wrap/unwrap
    assert enc.unwrap(dek_wrapped) == dek_plain

    # Column-level encryption with the unwrapped DEK
    column_value = b"sensitive transcript JSON"
    wire = enc.encrypt(column_value, dek_plain, associated_data=b"row-42")
    assert enc.decrypt(wire, dek_plain, associated_data=b"row-42") == column_value


def test_envelope_encryptor_aad_mismatch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    kek = secrets.token_bytes(DEK_BYTES)
    monkeypatch.setenv("OCR2R_KEK_B64", base64.b64encode(kek).decode())
    enc = EnvelopeEncryptor(EnvKEKProvider())
    dek_plain, _ = enc.new_tenant_dek_wrapped()
    wire = enc.encrypt(b"x", dek_plain, associated_data=b"row-1")
    with pytest.raises(CryptoError):
        enc.decrypt(wire, dek_plain, associated_data=b"row-2")


# ─── API keys ─────────────────────────────────────────────────
def test_generate_api_key_shape() -> None:
    live = generate_api_key(live=True)
    test = generate_api_key(live=False)
    assert live.startswith("sk_live_")
    assert test.startswith("sk_test_")
    assert len(live) > 20


def test_api_key_hash_verify() -> None:
    key = generate_api_key()
    h = hash_api_key(key)
    assert verify_api_key(key, h) is True
    assert verify_api_key("sk_test_NOPE", h) is False


def test_api_key_prefix_consistent() -> None:
    key = generate_api_key(live=True)
    assert api_key_prefix(key) == "sk_live_"


def test_api_key_hash_rejects_malformed() -> None:
    from ocr_to_report.adapters.crypto.api_keys import ApiKeyError  # noqa: PLC0415

    with pytest.raises(ApiKeyError):
        hash_api_key("not a real key")


# ─── HMAC signing ─────────────────────────────────────────────
def test_hmac_sign_verify_round_trip() -> None:
    secret = secrets.token_bytes(32)
    payload = b"webhook payload"
    header = hmac_sign(payload, secret)
    hmac_verify(payload, header, secret)


def test_hmac_verify_rejects_wrong_payload() -> None:
    secret = secrets.token_bytes(32)
    header = hmac_sign(b"original", secret)
    with pytest.raises(HmacError):
        hmac_verify(b"tampered", header, secret)


def test_hmac_verify_rejects_old_timestamp() -> None:
    secret = secrets.token_bytes(32)
    old_ts = int(time.time()) - 3600
    header = hmac_sign(b"x", secret, timestamp=old_ts)
    with pytest.raises(HmacError):
        hmac_verify(b"x", header, secret, replay_window_seconds=300)


def test_hmac_verify_disabled_replay_window() -> None:
    secret = secrets.token_bytes(32)
    old_ts = int(time.time()) - 3600
    header = hmac_sign(b"x", secret, timestamp=old_ts)
    # Disabled by setting replay_window_seconds=0
    hmac_verify(b"x", header, secret, replay_window_seconds=0)


def test_hmac_verify_malformed_header() -> None:
    with pytest.raises(HmacError):
        hmac_verify(b"x", "not_a_signature", b"k")

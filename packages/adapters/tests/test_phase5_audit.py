"""Audit hash-chain tests."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from ocr_to_report.adapters.audit import (
    AuditChainBroken,
    AuditEntry,
    canonicalize,
    next_entry,
    verify_chain,
)
from ocr_to_report.adapters.audit.chain import GENESIS_HASH


def _make(prev_hash: str, action: str = "test.action") -> AuditEntry:
    return next_entry(
        id=uuid4(),
        ts=datetime.now(tz=UTC),
        tenant_id=uuid4(),
        actor_type="api_key",
        actor_id_hash="a" * 64,
        action=action,
        resource_type="job",
        resource_id="job-1",
        ip="127.0.0.1",
        user_agent_hash="u" * 64,
        request_id="req-1",
        metadata={"k": "v"},
        prev_hash=prev_hash,
    )


def test_canonicalize_deterministic() -> None:
    a = canonicalize({"b": 2, "a": 1})
    b = canonicalize({"a": 1, "b": 2})
    assert a == b


def test_first_entry_uses_genesis() -> None:
    entry = _make(GENESIS_HASH)
    verify_chain([entry])  # passes


def test_chain_verifies_when_intact() -> None:
    e1 = _make(GENESIS_HASH)
    e2 = _make(e1.row_hash)
    e3 = _make(e2.row_hash)
    verify_chain([e1, e2, e3])


def test_chain_breaks_on_prev_hash_mismatch() -> None:
    e1 = _make(GENESIS_HASH)
    e2 = _make("0" * 64)  # wrong prev_hash (not e1.row_hash)
    with pytest.raises(AuditChainBroken):
        verify_chain([e1, e2])


def test_chain_breaks_on_row_mutation() -> None:
    e1 = _make(GENESIS_HASH)
    # Mutate the action — recompute would change the hash, but we keep
    # the original (stale) row_hash to simulate tampering
    tampered = dataclasses.replace(e1, action="evil.action")
    with pytest.raises(AuditChainBroken):
        verify_chain([tampered])


def test_chain_breaks_on_metadata_mutation() -> None:
    e1 = _make(GENESIS_HASH)
    tampered = dataclasses.replace(e1, metadata={"k": "evil"})
    with pytest.raises(AuditChainBroken):
        verify_chain([tampered])


def test_empty_chain_verifies_trivially() -> None:
    verify_chain([])


def test_long_chain_round_trip() -> None:
    prev = GENESIS_HASH
    entries = []
    for i in range(50):
        e = _make(prev, action=f"act.{i}")
        entries.append(e)
        prev = e.row_hash
    verify_chain(entries)

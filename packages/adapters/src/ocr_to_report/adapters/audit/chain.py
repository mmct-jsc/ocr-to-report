"""Hash chain construction + verification.

Pure functions — no I/O. The DB writer (Phase 5e) calls
:func:`next_entry` before insert; the verifier (Phase 5g cron) calls
:func:`verify_chain` over a fetched range of rows.

Hash input is the canonical JSON form (sorted keys, separators) of every
field except ``row_hash`` itself.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from ocr_to_report.core.errors.domain import OcrToReportError

if TYPE_CHECKING:
    from collections.abc import Iterable


GENESIS_HASH = "0" * 64
"""Sentinel for the very first row in a tenant's audit chain."""


class AuditChainBroken(OcrToReportError):  # noqa: N818
    """The hash chain failed integrity verification.

    Named *Broken* (not *Error*) because the condition is a domain-level
    invariant violation, not a generic runtime error.
    """

    status = 500
    type_uri = "https://errors.ocr-to-report/audit-chain-broken"
    title = "Audit chain integrity violation"


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """A single entry in the audit chain (pre-DB).

    ``row_hash`` is computed from the canonical JSON of every other
    field. The DB stores ``row_hash`` so future verifications don't need
    to re-canonicalize.
    """

    id: UUID
    ts: datetime
    tenant_id: UUID
    actor_type: str
    actor_id_hash: str
    action: str
    resource_type: str
    resource_id: str | None
    ip: str | None
    user_agent_hash: str | None
    request_id: str | None
    metadata: dict[str, Any]
    prev_hash: str
    row_hash: str

    def canonical_dict_for_hash(self) -> dict[str, Any]:
        """Return the dict whose SHA-256 forms ``row_hash`` (excludes itself)."""
        return {
            "id": str(self.id),
            "ts": self.ts.isoformat(),
            "tenant_id": str(self.tenant_id),
            "actor_type": self.actor_type,
            "actor_id_hash": self.actor_id_hash,
            "action": self.action,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "ip": self.ip,
            "user_agent_hash": self.user_agent_hash,
            "request_id": self.request_id,
            "metadata": self.metadata,
            "prev_hash": self.prev_hash,
        }


def canonicalize(payload: dict[str, Any]) -> bytes:
    """Deterministic JSON: sorted keys, no extra whitespace, ensure_ascii."""
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _row_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonicalize(payload)).hexdigest()


def next_entry(
    *,
    id: UUID,
    ts: datetime,
    tenant_id: UUID,
    actor_type: str,
    actor_id_hash: str,
    action: str,
    resource_type: str,
    resource_id: str | None,
    ip: str | None,
    user_agent_hash: str | None,
    request_id: str | None,
    metadata: dict[str, Any],
    prev_hash: str,
) -> AuditEntry:
    """Build the next entry in a tenant's chain.

    Pass ``prev_hash=GENESIS_HASH`` for the very first row in the chain.
    """
    payload = {
        "id": str(id),
        "ts": ts.isoformat(),
        "tenant_id": str(tenant_id),
        "actor_type": actor_type,
        "actor_id_hash": actor_id_hash,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "ip": ip,
        "user_agent_hash": user_agent_hash,
        "request_id": request_id,
        "metadata": metadata,
        "prev_hash": prev_hash,
    }
    return AuditEntry(
        id=id,
        ts=ts,
        tenant_id=tenant_id,
        actor_type=actor_type,
        actor_id_hash=actor_id_hash,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip=ip,
        user_agent_hash=user_agent_hash,
        request_id=request_id,
        metadata=metadata,
        prev_hash=prev_hash,
        row_hash=_row_hash(payload),
    )


def verify_chain(
    entries: Iterable[AuditEntry],
    *,
    expected_first_prev_hash: str = GENESIS_HASH,
) -> None:
    """Walk a tenant's audit chain (in chronological order) and raise
    :class:`AuditChainBroken` on any mismatch.

    Caller is responsible for ordering entries by timestamp / monotonic
    cursor before passing in.
    """
    prev_hash = expected_first_prev_hash
    for i, entry in enumerate(entries):
        if entry.prev_hash != prev_hash:
            raise AuditChainBroken(
                f"chain break at index {i}: prev_hash mismatch "
                f"(expected {prev_hash}, got {entry.prev_hash})",
                index=i,
                expected_prev_hash=prev_hash,
                actual_prev_hash=entry.prev_hash,
                entry_id=str(entry.id),
            )
        recomputed = _row_hash(entry.canonical_dict_for_hash())
        if recomputed != entry.row_hash:
            raise AuditChainBroken(
                f"chain break at index {i}: row_hash mismatch (row content has been altered)",
                index=i,
                expected_row_hash=recomputed,
                actual_row_hash=entry.row_hash,
                entry_id=str(entry.id),
            )
        prev_hash = entry.row_hash


__all__ = [
    "GENESIS_HASH",
    "AuditChainBroken",
    "AuditEntry",
    "canonicalize",
    "next_entry",
    "verify_chain",
]

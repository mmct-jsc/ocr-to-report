"""Hash-chained audit log primitives.

Each tenant's audit rows form an append-only chain: every row carries a
``prev_hash`` (the SHA-256 of the canonical JSON of the prior row) and a
``row_hash`` (its own SHA-256). A daily verifier walks the chain and
alerts on any mismatch — tampering with any historical row breaks the
chain at that row.

The actual SQLAlchemy table lives in ``adapters/db/models.py``; this
module is the pure-logic layer that builds rows and verifies chains.
"""

from ocr_to_report.adapters.audit.chain import (
    AuditChainBroken,
    AuditEntry,
    canonicalize,
    next_entry,
    verify_chain,
)

__all__ = [
    "AuditChainBroken",
    "AuditEntry",
    "canonicalize",
    "next_entry",
    "verify_chain",
]

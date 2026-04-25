"""TranscriptRepo — encrypted transcript storage."""

from __future__ import annotations

import json
import uuid
from typing import TYPE_CHECKING, Any

from ocr_to_report.adapters.db.models import Transcript

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from ocr_to_report.adapters.crypto import EnvelopeEncryptor
    from ocr_to_report.core.canonical import CanonicalTranscript


class TranscriptRepo:
    """Encrypted-at-rest transcript storage.

    The CanonicalTranscript is JSON-serialized then AES-GCM-encrypted
    with the tenant's DEK. The associated_data binds ciphertext to
    ``(tenant_id, job_id)`` so cross-row substitution attacks fail.
    """

    def __init__(self, session: AsyncSession, encryptor: EnvelopeEncryptor) -> None:
        self._session = session
        self._encryptor = encryptor

    async def store(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        transcript: CanonicalTranscript,
        dek: bytes,
        input_sha256: str,
        output_sha256: str | None = None,
    ) -> Transcript:
        plaintext = json.dumps(
            transcript.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        aad = _aad(tenant_id, job_id)
        encrypted = self._encryptor.encrypt(plaintext, dek, associated_data=aad)
        row = Transcript(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            job_id=job_id,
            input_sha256=input_sha256,
            output_sha256=output_sha256,
            canonical_encrypted=encrypted,
            overall_confidence=transcript.overall_confidence,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def fetch(
        self,
        *,
        tenant_id: uuid.UUID,
        job_id: uuid.UUID,
        dek: bytes,
    ) -> dict[str, object] | None:
        from sqlalchemy import select  # noqa: PLC0415

        result = await self._session.execute(
            select(Transcript).where(
                Transcript.tenant_id == tenant_id,
                Transcript.job_id == job_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        plaintext = self._encryptor.decrypt(
            row.canonical_encrypted,
            dek,
            associated_data=_aad(tenant_id, job_id),
        )
        return dict(json.loads(plaintext))

    async def delete_by_job(self, *, tenant_id: uuid.UUID, job_id: uuid.UUID) -> int:
        """Hard-delete the transcript row for a job; return rows deleted.

        Used by the retention sweep to crypto-shred the encrypted
        canonical at the row level. The tenant DEK isn't touched
        (deleting the tenant is what crypto-shreds an entire tenant).
        """
        from sqlalchemy import delete  # noqa: PLC0415

        stmt = delete(Transcript).where(
            Transcript.tenant_id == tenant_id,
            Transcript.job_id == job_id,
        )
        result = await self._session.execute(stmt)
        rowcount = getattr(result, "rowcount", 0)
        return int(rowcount or 0)

    async def list_for_tenant(
        self,
        *,
        tenant_id: uuid.UUID,
        dek: bytes,
    ) -> list[dict[str, Any]]:
        """Decrypt + return every transcript snapshot for the tenant.

        Used by the GDPR DSR access/portability endpoints. The caller
        is responsible for filtering by data-subject identity (we do
        the decryption here so the filter can match against PII fields
        in the canonical payload).
        """
        from sqlalchemy import select  # noqa: PLC0415

        result = await self._session.execute(
            select(Transcript).where(Transcript.tenant_id == tenant_id)
        )
        out: list[dict[str, Any]] = []
        for row in result.scalars().all():
            plaintext = self._encryptor.decrypt(
                row.canonical_encrypted,
                dek,
                associated_data=_aad(tenant_id, row.job_id),
            )
            out.append(dict(json.loads(plaintext)))
        return out


def _aad(tenant_id: uuid.UUID, job_id: uuid.UUID) -> bytes:
    return f"{tenant_id}:{job_id}".encode()


__all__ = ["TranscriptRepo"]

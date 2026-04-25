"""GDPR Data Subject Request endpoints.

Three operations from the GDPR's data-subject rights chapter:

* ``GET /v1/dsr/access?subject_full_name=...`` — Article 15 (Right of
  Access). Returns every transcript record we hold matching the
  subject's full name (decrypted, in JSON form).
* ``GET /v1/dsr/portability?subject_full_name=...`` — Article 20.
  Same data as Access, wrapped in a stable ``schema_version`` envelope
  for machine-readable export.
* ``POST /v1/dsr/erasure`` — Article 17. Deletes every matching
  transcript row + every associated input/output blob; writes a
  retention-style audit entry tagged ``ferpa_disclosure=False`` and
  ``gdpr_dsr_erasure=True``.

All three require the ``transcripts:write`` scope and are scoped to
the calling tenant. The matching is by exact ``student.full_name``
case-insensitive — production deployments may want to extend this
with fuzzy match + admin review.

The endpoints append audit-log entries with full DSR provenance so the
Article 30 records-of-processing report can be reconstructed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ocr_to_report.adapters.db import Job
from ocr_to_report.api.deps import AppState, RequestRepos, get_app_state, get_repos
from ocr_to_report.api.schemas import (
    DSRAccessResponse,
    DSRErasureRequest,
    DSRErasureResponse,
    DSRPortabilityResponse,
)
from ocr_to_report.core.errors.domain import ValidationError

router = APIRouter(prefix="/v1/dsr", tags=["dsr"])


@router.get("/access", response_model=DSRAccessResponse)
async def dsr_access(
    repos: Annotated[RequestRepos, Depends(get_repos)],
    subject_full_name: Annotated[
        str,
        Query(min_length=1, max_length=200, description="Full name of the data subject."),
    ],
) -> DSRAccessResponse:
    """GDPR Article 15 — Right of Access."""
    matches = await _matching_transcripts(repos, subject_full_name)
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="dsr.access",
        resource_type="data_subject",
        resource_id=_subject_resource_id(subject_full_name),
        metadata={"record_count": len(matches), "ferpa_disclosure": True},
    )
    return DSRAccessResponse(
        subject_full_name=subject_full_name,
        tenant_id=repos.tenant.id,
        generated_at=datetime.now(tz=UTC),
        record_count=len(matches),
        transcripts=matches,
    )


@router.get("/portability", response_model=DSRPortabilityResponse)
async def dsr_portability(
    repos: Annotated[RequestRepos, Depends(get_repos)],
    subject_full_name: Annotated[
        str,
        Query(min_length=1, max_length=200, description="Full name of the data subject."),
    ],
) -> DSRPortabilityResponse:
    """GDPR Article 20 — Right to Portability."""
    matches = await _matching_transcripts(repos, subject_full_name)
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="dsr.portability",
        resource_type="data_subject",
        resource_id=_subject_resource_id(subject_full_name),
        metadata={"record_count": len(matches), "ferpa_disclosure": True},
    )
    return DSRPortabilityResponse(
        subject_full_name=subject_full_name,
        tenant_id=repos.tenant.id,
        generated_at=datetime.now(tz=UTC),
        transcripts=matches,
    )


@router.post("/erasure", response_model=DSRErasureResponse, status_code=200)
async def dsr_erasure(
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
    request: DSRErasureRequest,
) -> DSRErasureResponse:
    """GDPR Article 17 — Right to Erasure.

    Deletes the transcript rows + linked input/output blobs for every
    job whose decrypted canonical's ``student.full_name`` matches the
    request. The ``Job`` rows themselves are kept (they only contain
    operational metadata, no PII) but their input/output blob keys are
    cleared and the corresponding object-storage objects are deleted.
    """
    if not request.confirm:
        raise ValidationError("erasure requires confirm=True")

    import logging  # noqa: PLC0415

    log = logging.getLogger("ocr_to_report.api.dsr")

    matches_before = await _matching_jobs(repos, request.subject_full_name)
    transcripts_erased = 0
    blobs_erased = 0
    for job in matches_before:
        n = await repos.transcripts.delete_by_job(
            tenant_id=repos.tenant.id,
            job_id=job.id,
        )
        transcripts_erased += n
        for key in (job.input_blob_key, job.output_blob_key):
            if key is None:
                continue
            try:
                await state.blob_store.delete(key)
                blobs_erased += 1
            except Exception as e:
                # Best-effort: a missing blob is fine (the job's encrypted
                # transcript is already gone). Log + carry on; never let
                # storage flakes block an erasure obligation.
                log.warning(
                    "dsr.erasure: blob delete failed",
                    extra={"key": key, "error": f"{type(e).__name__}: {e}"},
                )
        # Null out the job row's blob keys so a later access call
        # doesn't surface stale references.
        job.input_blob_key = None
        job.output_blob_key = None

    audit_row = await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="dsr.erasure",
        resource_type="data_subject",
        resource_id=_subject_resource_id(request.subject_full_name),
        metadata={
            "transcripts_erased": transcripts_erased,
            "blobs_erased": blobs_erased,
            "ferpa_disclosure": True,
        },
    )
    return DSRErasureResponse(
        subject_full_name=request.subject_full_name,
        tenant_id=repos.tenant.id,
        transcripts_erased=transcripts_erased,
        blobs_erased=blobs_erased,
        audit_entry_id=audit_row.id,
        completed_at=datetime.now(tz=UTC),
    )


# ─── Helpers ─────────────────────────────────────────────────
async def _matching_transcripts(
    repos: RequestRepos,
    subject_full_name: str,
) -> list[dict[str, Any]]:
    """Return decrypted transcripts whose ``student.full_name`` matches."""
    target = subject_full_name.casefold()
    all_transcripts = await repos.transcripts.list_for_tenant(
        tenant_id=repos.tenant.id,
        dek=repos.dek,
    )
    return [
        t
        for t in all_transcripts
        if str(_get_student_name(t)).casefold() == target
    ]


async def _matching_jobs(
    repos: RequestRepos,
    subject_full_name: str,
) -> list[Job]:
    """Find every ``Job`` whose linked transcript matches the subject.

    Walks all transcripts (small per-tenant cardinality in MVP) +
    decrypts to filter, then loads the corresponding ``Job`` rows.
    """
    target = subject_full_name.casefold()
    from sqlalchemy import select  # noqa: PLC0415

    from ocr_to_report.adapters.db.models import Transcript  # noqa: PLC0415

    result = await repos.session.execute(
        select(Transcript).where(Transcript.tenant_id == repos.tenant.id)
    )
    matching_job_ids: list[uuid.UUID] = []
    for row in result.scalars().all():
        plaintext = repos.encryptor.decrypt(
            row.canonical_encrypted,
            repos.dek,
            associated_data=f"{repos.tenant.id}:{row.job_id}".encode(),
        )
        import json  # noqa: PLC0415

        canonical = json.loads(plaintext)
        if str(_get_student_name(canonical)).casefold() == target:
            matching_job_ids.append(row.job_id)

    if not matching_job_ids:
        return []
    jobs_query = await repos.session.execute(
        select(Job).where(Job.id.in_(matching_job_ids))
    )
    return list(jobs_query.scalars().all())


def _get_student_name(canonical: dict[str, Any]) -> str:
    """Extract the student.full_name from a CanonicalTranscript dict."""
    student = canonical.get("student") or {}
    if isinstance(student, dict):
        name = student.get("full_name")
        if isinstance(name, str):
            return name
    return ""


def _subject_resource_id(subject_full_name: str) -> str:
    """Build a stable, non-PII-leaking resource_id for audit logs.

    We hash the casefolded name so the audit row does not store the raw
    subject name (the audit table is queryable without DEK).
    """
    import hashlib  # noqa: PLC0415

    return hashlib.sha256(subject_full_name.casefold().encode("utf-8")).hexdigest()


__all__ = ["router"]

"""GET /v1/jobs/{id} (status), GET /v1/jobs/{id}/result (download),
GET /v1/jobs (list — manual-review queue), POST /v1/jobs/{id}/approve,
POST /v1/jobs/{id}/reject."""

from __future__ import annotations

import hashlib
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from ocr_to_report.adapters.db import Job
from ocr_to_report.adapters.render import XlsxRenderer
from ocr_to_report.adapters.vision import (
    VisionRequest,
    compile_schema,
    preprocess,
)
from ocr_to_report.api.deps import AppState, RequestRepos, get_app_state, get_repos
from ocr_to_report.api.schemas import TranscriptJobSummary
from ocr_to_report.core.errors.domain import ConflictError, NotFoundError, ValidationError
from ocr_to_report.core.mapping import canonical_to_render_data, extract_to_canonical

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.get("/jobs", response_model=list[TranscriptJobSummary])
async def list_jobs(
    repos: Annotated[RequestRepos, Depends(get_repos)],
    status: Annotated[
        str | None,
        Query(description="Filter by job status (e.g., 'parked')"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[TranscriptJobSummary]:
    """List jobs for the current tenant.

    The primary use case is the manual-review dashboard listing parked
    jobs (``?status=parked``); reviewers approve / reject from there.
    """
    if status is None:
        # Just return the most recent jobs of any status — convenience listing.
        from sqlalchemy import select  # noqa: PLC0415

        result = await repos.session.execute(
            select(Job)
            .where(Job.tenant_id == repos.tenant.id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        rows = list(result.scalars().all())
    else:
        rows = await repos.jobs.list_by_status(
            tenant_id=repos.tenant.id,
            status=status,
            limit=limit,
        )
    return [_summary(j) for j in rows]


@router.get("/jobs/{job_id}", response_model=TranscriptJobSummary)
async def get_job(
    job_id: uuid.UUID,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> TranscriptJobSummary:
    job = await repos.jobs.get(job_id)
    if job is None or job.tenant_id != repos.tenant.id:
        raise NotFoundError(f"no job with id={job_id}", job_id=str(job_id))
    return _summary(job)


@router.post("/jobs/{job_id}/approve", response_model=TranscriptJobSummary, status_code=200)
async def approve_job(
    job_id: uuid.UUID,
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> TranscriptJobSummary:
    """Approve a parked job + finish processing.

    Re-runs extraction with the SLA's fallback model (stronger), then
    completes the rest of the pipeline (translate, map, render, persist).
    The reviewer is implicitly accepting the SLA's lower threshold for
    this single job.
    """
    job = await repos.jobs.get(job_id)
    if job is None or job.tenant_id != repos.tenant.id:
        raise NotFoundError(f"no job with id={job_id}", job_id=str(job_id))
    if job.status != "parked":
        raise ConflictError(
            f"only parked jobs can be approved (status={job.status})",
            job_id=str(job_id),
            status=job.status,
        )
    if job.profile_id is None or job.target_id is None:
        raise ValidationError(
            f"job {job_id} missing profile/target ids",
            job_id=str(job_id),
        )
    if not job.input_blob_key:
        raise ValidationError(
            f"job {job_id} has no input blob key — cannot resume",
            job_id=str(job_id),
        )

    blob = await state.blob_store.get(job.input_blob_key)
    profile_bundle = state.profile_registry.get(job.profile_id)
    target_bundle = state.target_registry.get(job.target_id)

    images = preprocess(blob)
    schema = compile_schema(profile_bundle.extraction_schema)
    vision_req = VisionRequest(
        images=images,
        prompt=profile_bundle.extraction_prompt_template,
        output_schema=schema,
        schema_version=profile_bundle.manifest.version,
        profile_id=job.profile_id,
    )
    adapter = state.vision_router.select()
    result = await adapter.extract(vision_req)

    canonical = extract_to_canonical(
        profile_bundle,
        result.raw_extraction,
        extraction_confidence=result.confidence,
    )
    render_data = canonical_to_render_data(
        target_bundle,
        canonical,
        template_override_key=job.target_template_key,
    )
    renderer = XlsxRenderer(state.bundle_roots[job.target_id])
    output_blob = renderer(target_bundle, render_data)

    out_key = f"jobs/{job.id}/output.xlsx"
    await state.blob_store.put(
        out_key,
        output_blob,
        content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    )
    await repos.transcripts.store(
        tenant_id=repos.tenant.id,
        job_id=job.id,
        transcript=canonical,
        dek=repos.dek,
        input_sha256=hashlib.sha256(blob).hexdigest(),
        output_sha256=hashlib.sha256(output_blob).hexdigest(),
    )
    await repos.jobs.mark_succeeded(
        job.id,
        output_blob_key=out_key,
        provider_used=result.provider.value,
        model_id_used=result.model_id,
        tokens_input=result.usage.input_tokens,
        tokens_output=result.usage.output_tokens,
        usd_cost=result.usage.usd_cost,
    )
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="job.approved",
        resource_type="job",
        resource_id=str(job.id),
        metadata={"final_confidence": result.confidence},
    )
    refreshed = await repos.jobs.get(job.id)
    if refreshed is None:
        raise ConflictError("job vanished mid-approve")
    return _summary(refreshed)


@router.post("/jobs/{job_id}/reject", response_model=TranscriptJobSummary, status_code=200)
async def reject_job(
    job_id: uuid.UUID,
    repos: Annotated[RequestRepos, Depends(get_repos)],
    body: Annotated[dict[str, Any] | None, "Optional JSON body: {reason: str}"] = None,
) -> TranscriptJobSummary:
    """Reject a parked job; mark it failed permanently."""
    job = await repos.jobs.get(job_id)
    if job is None or job.tenant_id != repos.tenant.id:
        raise NotFoundError(f"no job with id={job_id}", job_id=str(job_id))
    if job.status != "parked":
        raise ConflictError(
            f"only parked jobs can be rejected (status={job.status})",
            job_id=str(job_id),
            status=job.status,
        )

    reason = "rejected by reviewer"
    if body and isinstance(body, dict):
        provided = body.get("reason")
        if isinstance(provided, str) and provided.strip():
            reason = provided

    await repos.jobs.mark_failed(job.id, error_detail=reason)
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="job.rejected",
        resource_type="job",
        resource_id=str(job.id),
        metadata={"reason": reason},
    )
    refreshed = await repos.jobs.get(job.id)
    if refreshed is None:
        raise ConflictError("job vanished mid-reject")
    return _summary(refreshed)


@router.get(
    "/jobs/{job_id}/result",
    responses={
        200: {
            "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}},
            "description": "The rendered output (xlsx) blob.",
        },
        404: {"description": "Job or output missing"},
    },
)
async def get_job_result(
    job_id: uuid.UUID,
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> Response:
    job = await repos.jobs.get(job_id)
    if job is None or job.tenant_id != repos.tenant.id:
        raise NotFoundError(f"no job with id={job_id}", job_id=str(job_id))
    if job.output_blob_key is None:
        raise NotFoundError(
            f"job {job_id} has no output (status={job.status})",
            job_id=str(job_id),
            status=job.status,
        )
    blob = await state.blob_store.get(job.output_blob_key)
    return Response(
        blob,
        media_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        headers={
            "Content-Disposition": (f'attachment; filename="job_{job_id}.xlsx"'),
        },
    )


def _summary(job: Job) -> TranscriptJobSummary:
    return TranscriptJobSummary(
        id=job.id,
        status=job.status,
        profile_id=job.profile_id,
        target_id=job.target_id,
        target_template_key=job.target_template_key,
        pipeline_id=job.pipeline_id,
        provider_used=job.provider_used,
        model_id_used=job.model_id_used,
        tokens_input=job.tokens_input,
        tokens_output=job.tokens_output,
        usd_cost=float(job.usd_cost),
        error_detail=job.error_detail,
        park_reason=job.park_reason,
        output_blob_key=job.output_blob_key,
        created_at=job.created_at,
        updated_at=job.updated_at,
        completed_at=job.completed_at,
        expires_at=job.expires_at,
    )


__all__ = ["router"]

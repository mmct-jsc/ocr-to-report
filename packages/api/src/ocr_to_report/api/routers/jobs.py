"""GET /v1/jobs/{id} (status) and GET /v1/jobs/{id}/result (download)."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import Response

from ocr_to_report.adapters.db import Job
from ocr_to_report.api.deps import AppState, RequestRepos, get_app_state, get_repos
from ocr_to_report.api.schemas import TranscriptJobSummary
from ocr_to_report.core.errors.domain import NotFoundError

router = APIRouter(prefix="/v1", tags=["jobs"])


@router.get("/jobs/{job_id}", response_model=TranscriptJobSummary)
async def get_job(
    job_id: uuid.UUID,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> TranscriptJobSummary:
    job = await repos.jobs.get(job_id)
    if job is None or job.tenant_id != repos.tenant.id:
        raise NotFoundError(f"no job with id={job_id}", job_id=str(job_id))
    return _summary(job)


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

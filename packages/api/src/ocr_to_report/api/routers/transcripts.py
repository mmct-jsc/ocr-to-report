"""POST /v1/transcripts — sync extract + render."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, UploadFile

from ocr_to_report.adapters.db import Job
from ocr_to_report.adapters.render import XlsxRenderer
from ocr_to_report.adapters.vision import (
    ExtractionResult,
    InMemoryAsyncCache,
    VisionAdapter,
    VisionRequest,
    compile_schema,
    deserialize_result,
    make_cache_key,
    preprocess,
    serialize_result,
)
from ocr_to_report.api.deps import (
    AppState,
    RequestRepos,
    get_app_state,
    get_repos,
)
from ocr_to_report.api.schemas import (
    TranscriptExtractionResponse,
    TranscriptJobSummary,
)
from ocr_to_report.core.errors.domain import (
    ConflictError,
    PayloadTooLargeError,
    ValidationError,
    VisionProviderError,
)
from ocr_to_report.core.mapping import canonical_to_render_data, extract_to_canonical
from ocr_to_report.core.pipeline.protocol import StepStatus

router = APIRouter(prefix="/v1", tags=["transcripts"])


@router.post(
    "/transcripts",
    response_model=TranscriptExtractionResponse,
    status_code=200,
    responses={
        400: {"description": "Validation failed"},
        401: {"description": "Authentication required"},
        413: {"description": "Payload too large"},
        503: {"description": "No vision provider available"},
    },
)
async def create_transcript(
    state: Annotated[AppState, Depends(get_app_state)],
    repos: Annotated[RequestRepos, Depends(get_repos)],
    file: Annotated[UploadFile, File(description="PDF or image of the transcript")],
    profile_id: Annotated[str, Form(description="Source profile id")],
    target_id: Annotated[str, Form(description="Target system id")],
    target_template_key: Annotated[
        str | None,
        Form(description="Target template key; defaults to year-mapped"),
    ] = None,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", description="24h replay-safe POST identifier"),
    ] = None,
) -> TranscriptExtractionResponse:
    """Sync extract + render. Reads the upload, runs the pipeline, and
    returns the canonical extraction + a job summary. The rendered
    output blob is fetched via ``GET /v1/jobs/{id}/result``.
    """
    blob = await file.read()
    if len(blob) > state.settings.max_upload_bytes:
        raise PayloadTooLargeError(
            f"upload is {len(blob)} bytes; max is {state.settings.max_upload_bytes}",
        )

    request_hash = hashlib.sha256(blob).hexdigest() + ":" + profile_id + ":" + target_id

    # Idempotency replay
    if idempotency_key is not None:
        prior = await repos.idempotency.get(
            tenant_id=repos.tenant.id,
            key=idempotency_key,
            request_hash=request_hash,
        )
        if prior is not None:
            existing_job = await repos.jobs.get_by_idempotency(repos.tenant.id, idempotency_key)
            if existing_job is not None:
                return _summary_from_cached(existing_job, prior.response_body)

    # Bundle lookups
    profile_bundle = state.profile_registry.get(profile_id)
    target_bundle = state.target_registry.get(target_id)

    # Job row (pending)
    job = await repos.jobs.create(
        tenant_id=repos.tenant.id,
        profile_id=profile_id,
        target_id=target_id,
        target_template_key=target_template_key,
        idempotency_key=idempotency_key,
    )
    await repos.jobs.mark_running(job.id)
    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",  # populated by the auth middleware in v1.1
        action="transcript.create",
        resource_type="job",
        resource_id=str(job.id),
    )

    try:
        # 1. Preprocess
        images = preprocess(blob)

        # 2. Vision extract (with result cache)
        adapter = state.vision_router.select()
        schema = compile_schema(profile_bundle.extraction_schema)
        vision_req = VisionRequest(
            images=images,
            prompt=profile_bundle.extraction_prompt_template,
            output_schema=schema,
            schema_version=profile_bundle.manifest.version,
            profile_id=profile_id,
        )
        result = await _extract_with_cache(adapter, vision_req, state.result_cache)

        # 3. Translate → canonical
        canonical = extract_to_canonical(
            profile_bundle,
            result.raw_extraction,
            extraction_confidence=result.confidence,
        )

        # 4. Map → render data
        render_data = canonical_to_render_data(
            target_bundle,
            canonical,
            template_override_key=target_template_key,
        )

        # 5. Render xlsx
        renderer = XlsxRenderer(state.bundle_roots[target_id])
        output_blob = renderer(target_bundle, render_data)

        # 6. Persist input + output blobs
        in_key = f"jobs/{job.id}/input"
        out_key = f"jobs/{job.id}/output.xlsx"
        await state.blob_store.put(in_key, blob)
        await state.blob_store.put(
            out_key,
            output_blob,
            content_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        )

        # 7. Encrypt + persist canonical transcript
        await repos.transcripts.store(
            tenant_id=repos.tenant.id,
            job_id=job.id,
            transcript=canonical,
            dek=repos.dek,
            input_sha256=hashlib.sha256(blob).hexdigest(),
            output_sha256=hashlib.sha256(output_blob).hexdigest(),
        )

        # 8. Job → succeeded
        await repos.jobs.mark_succeeded(
            job.id,
            output_blob_key=out_key,
            provider_used=result.provider.value,
            model_id_used=result.model_id,
            tokens_input=result.usage.input_tokens,
            tokens_output=result.usage.output_tokens,
            usd_cost=result.usage.usd_cost,
        )

        # 9. Usage rollup (per-month period)
        period_start, period_end = _current_month_period()
        await repos.usage.increment(
            tenant_id=repos.tenant.id,
            period_start=period_start,
            period_end=period_end,
            transcripts=1,
            tokens_input=result.usage.input_tokens,
            tokens_output=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_input_tokens,
            cache_creation_tokens=result.usage.cache_creation_input_tokens,
            usd_cost=result.usage.usd_cost,
        )

        await repos.audit.append(
            tenant_id=repos.tenant.id,
            actor_type="api_key",
            actor_id_hash="",
            action="transcript.completed",
            resource_type="job",
            resource_id=str(job.id),
            metadata={"provider": result.provider.value, "model": result.model_id},
        )
    except (ValidationError, VisionProviderError) as e:
        await repos.jobs.mark_failed(job.id, error_detail=e.detail or str(e))
        raise
    except Exception as e:
        await repos.jobs.mark_failed(job.id, error_detail=f"{type(e).__name__}: {e}")
        raise

    refreshed = await repos.jobs.get(job.id)
    if refreshed is None:
        raise ConflictError("job vanished mid-request — investigate")

    summary = _build_summary(refreshed)
    response = TranscriptExtractionResponse(
        job=summary,
        extraction=canonical.model_dump(mode="json"),
        overall_confidence=canonical.overall_confidence,
        warnings=list(render_data.warnings) + list(canonical.extraction_warnings),
    )

    # Idempotency cache (24h)
    if idempotency_key is not None:
        body = response.model_dump_json().encode("utf-8")
        expires = datetime.now(tz=UTC).fromtimestamp(
            datetime.now(tz=UTC).timestamp() + state.settings.idempotency_ttl_seconds,
            tz=UTC,
        )
        await repos.idempotency.store(
            tenant_id=repos.tenant.id,
            key=idempotency_key,
            request_hash=request_hash,
            response_status=200,
            response_body=body,
            response_content_type="application/json",
            expires_at=expires,
        )

    return response


# ─── Helpers ──────────────────────────────────────────────────
async def _extract_with_cache(
    adapter: VisionAdapter,
    request: VisionRequest,
    cache: InMemoryAsyncCache,
) -> ExtractionResult:
    cache_key = make_cache_key(request.images, adapter.name, request.schema_version)
    blob = await cache.get(cache_key)
    if blob is not None:
        return deserialize_result(blob)
    result = await adapter.extract(request)
    await cache.set(cache_key, serialize_result(result), ttl_seconds=3600)
    return result


def _summary_from_cached(job: Job, body: bytes) -> TranscriptExtractionResponse:
    import json  # noqa: PLC0415

    return TranscriptExtractionResponse.model_validate(json.loads(body))


def _build_summary(job: Job) -> TranscriptJobSummary:
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


def _current_month_period() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


# Suppress unused-import warnings (used as types in helpers above).
_ = StepStatus

__all__ = ["router"]

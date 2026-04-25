"""GET /v1/usage — current period token + cost rollup."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from ocr_to_report.api.deps import RequestRepos, get_repos
from ocr_to_report.api.schemas import UsageResponse

router = APIRouter(prefix="/v1", tags=["usage"])


@router.get("/usage", response_model=UsageResponse)
async def get_usage(
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> UsageResponse:
    period_start, period_end = _current_month_period()
    row = await repos.usage.get_period(
        tenant_id=repos.tenant.id,
        period_start=period_start,
        period_end=period_end,
    )
    if row is None:
        return UsageResponse(
            period_start=period_start,
            period_end=period_end,
            transcripts_processed=0,
            tokens_input=0,
            tokens_output=0,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            usd_cost=0.0,
        )
    return UsageResponse(
        period_start=row.period_start,
        period_end=row.period_end,
        transcripts_processed=row.transcripts_processed,
        tokens_input=row.tokens_input,
        tokens_output=row.tokens_output,
        cache_read_tokens=row.cache_read_tokens,
        cache_creation_tokens=row.cache_creation_tokens,
        usd_cost=float(row.usd_cost),
    )


def _current_month_period() -> tuple[datetime, datetime]:
    now = datetime.now(tz=UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


__all__ = ["router"]

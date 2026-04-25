"""Usage endpoint schema."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UsageResponse(BaseModel):
    """GET /v1/usage response body."""

    model_config = ConfigDict(extra="forbid")

    period_start: datetime
    period_end: datetime
    transcripts_processed: int
    tokens_input: int
    tokens_output: int
    cache_read_tokens: int
    cache_creation_tokens: int
    usd_cost: float


__all__ = ["UsageResponse"]

# syntax=docker/dockerfile:1.9
# OCR-to-Report Worker — same base as API, different entrypoint.

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

WORKDIR /build

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock* ./
COPY packages/core/pyproject.toml      packages/core/pyproject.toml
COPY packages/adapters/pyproject.toml  packages/adapters/pyproject.toml
COPY packages/api/pyproject.toml       packages/api/pyproject.toml
COPY packages/worker/pyproject.toml    packages/worker/pyproject.toml
COPY packages/cli/pyproject.toml       packages/cli/pyproject.toml
COPY packages/sdk_py/pyproject.toml    packages/sdk_py/pyproject.toml
COPY packages/mcp/pyproject.toml       packages/mcp/pyproject.toml

COPY packages/ packages/

RUN uv sync --no-dev --package ocr-to-report-worker --frozen 2>/dev/null \
 || uv sync --no-dev --package ocr-to-report-worker

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app -g 10001 \
 && useradd  -r -u 10001 -g app -d /app -s /sbin/nologin app

WORKDIR /app

COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/packages /app/packages
COPY profiles/   /app/profiles/
COPY targets/    /app/targets/
COPY pipelines/  /app/pipelines/
COPY sla-tiers/  /app/sla-tiers/

ARG GIT_SHA=dev
ARG BUILD_TIME=dev
ENV OCR2R_GIT_SHA=$GIT_SHA \
    OCR2R_BUILD_TIME=$BUILD_TIME

USER app

CMD ["python", "-m", "ocr_to_report.worker"]

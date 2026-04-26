# syntax=docker/dockerfile:1.9
# OCR-to-Report API — multi-stage, non-root, slim runtime.

# ─────────────────────────── Stage 1: builder ────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_CACHE=1

# uv (pinned)
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv

WORKDIR /build

# OS build deps (kept minimal, pinned via Debian repo)
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy workspace manifests first for layer cache efficiency
COPY pyproject.toml uv.lock* ./
COPY packages/core/pyproject.toml      packages/core/pyproject.toml
COPY packages/adapters/pyproject.toml  packages/adapters/pyproject.toml
COPY packages/api/pyproject.toml       packages/api/pyproject.toml
COPY packages/worker/pyproject.toml    packages/worker/pyproject.toml
COPY packages/cli/pyproject.toml       packages/cli/pyproject.toml
COPY packages/sdk_py/pyproject.toml    packages/sdk_py/pyproject.toml
COPY packages/mcp/pyproject.toml       packages/mcp/pyproject.toml

# Source needed for editable install of workspace members
COPY packages/ packages/

# Install runtime deps (no dev) into a venv
RUN uv sync --no-dev --package ocr-to-report-api --frozen 2>/dev/null \
 || uv sync --no-dev --package ocr-to-report-api

# ─────────────────────────── Stage 2: runtime ────────────────
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    OCR2R_API_HOST=0.0.0.0 \
    OCR2R_API_PORT=8000

# Runtime OS deps (kept minimal). poppler-utils backs pdf2image's
# PDF -> PNG pre-processor; without it any PDF upload returns 400.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        libpq5 \
        ca-certificates \
        curl \
        poppler-utils \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app -g 10001 \
 && useradd  -r -u 10001 -g app -d /app -s /sbin/nologin app

WORKDIR /app

# Copy the venv + the workspace source. The venv was built with editable
# installs whose .pth files point at /build/packages/.../src — keep that
# path stable in the runtime stage so the imports resolve. /build is
# never written to at runtime (the rootfs is read-only in compose).
COPY --from=builder /build/.venv /app/.venv
COPY --from=builder /build/packages /build/packages

# Profiles, targets, pipelines, sla-tiers — read at runtime
COPY profiles/   /app/profiles/
COPY targets/    /app/targets/
COPY pipelines/  /app/pipelines/
COPY sla-tiers/  /app/sla-tiers/

# Build metadata (set at build time via ARG)
ARG GIT_SHA=dev
ARG BUILD_TIME=dev
ENV OCR2R_GIT_SHA=$GIT_SHA \
    OCR2R_BUILD_TIME=$BUILD_TIME

USER app

EXPOSE 8000

# Healthcheck via the same /v1/health endpoint
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/v1/health || exit 1

CMD ["python", "-m", "ocr_to_report.api"]

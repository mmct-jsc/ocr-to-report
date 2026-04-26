# Changelog

All notable changes to OCR-to-Report. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/).

## [0.1.0+ui] — 2026-04-26

Post-tag bring-up: live-stack validation against real Anthropic, end-to-end
flow verified, web Operations Console added.

### Added

- **Web Operations Console** (`web/`) — Vite + React + Tailwind SPA driven
  by the TypeScript SDK. Pages: dashboard (KPIs + recent jobs + manual-
  review queue), process (drag-and-drop upload), jobs list + detail,
  webhooks, GDPR DSR (access / portability / erasure with type-to-confirm),
  templates catalog, settings. Light + dark themes, toast system, live
  API health pulse. Screenshots in `docs/ui/`.
- **`ocr-to-report bootstrap`** CLI — seeds a tenant + API key against
  the configured `OCR2R_DATABASE_URL`. Lets `docker compose up` smoke
  the whole stack without writing SQL.
- **`docs/BUDGET.md`** — production cost model grounded in a real
  benchmark ($0.031 / page on Standard with fallback, ~$0.005 on Haiku-
  only) plus per-tier projections and infra estimates.

### Fixed

Live-stack bugs surfaced when running the full Polish→US-HS path against
a real Anthropic key:

- **Dockerfile editable install paths**: `python -m ocr_to_report.api`
  crash-looped because the venv's `.pth` files pointed at
  `/build/packages/.../src` while the runtime stage copied source to
  `/app/packages`. Keep source at `/build/packages` in the runtime image
  in both `docker/api.Dockerfile` and `docker/worker.Dockerfile`.
- **`docker-compose.yml`**: scaffolded `worker` service was never wired
  up; `OCR2R_BLOB_BACKEND=s3` was missing so the API silently fell back
  to local-fs even with MinIO running.
- **Stub vision adapters** raised raw `NotImplementedError`, which
  leaked as 500 with a stack trace. Replaced with
  `ProviderNotConfiguredError` (HTTP 503, problem+json).
- **Transcripts router** committed `mark_failed` after the outer
  `tenant_scoped_session` rollback wiped the row. 503s reached users
  but the failed job vanished from the DB. Catch every
  `OcrToReportError`, explicit-commit before re-raise.
- **`ApiKeyRepo.authenticate`** malformed bearer tokens raised
  `ApiKeyError` → 500; now uniformly map to 401.
- **Audit chain ordering**: `verify_for_tenant` ordered by `(ts, id)`
  with a random UUID PK; same-microsecond inserts scrambled the chain
  and the verifier raised false `AuditChainBroken`. Walk the chain by
  `prev_hash` → `row_hash` linkage instead.
- **API container missing `poppler-utils`**: every PDF upload returned
  400 from `pdf2image`. Now installed in both Dockerfiles.
- **Anthropic structured-output schema constraints**: the platform
  rejects `minimum`/`maximum` on numbers and only accepts the literal
  `false` for `additionalProperties`. The `_meta` envelope dropped
  numeric bounds (clamps on read instead) and dropped the
  `field_confidences` map (overall confidence + warnings still drive
  the SLA gate).
- **`idempotency_keys.request_hash`** column was VARCHAR(64) but the
  value is `<sha256>:<profile_id>:<target_id>` (~100+ chars). Widened
  to VARCHAR(256). Existing Postgres needs `ALTER TABLE
  idempotency_keys ALTER COLUMN request_hash TYPE VARCHAR(256);`.
- **TypeScript SDK** — `new URL(this.baseUrl + path)` threw when
  `baseUrl` was relative (`/api`); anchor to `window.location.origin`.
  Storing the unbound global `fetch` and calling it via
  `this.fetchImpl(...)` raised "Illegal invocation" in browsers; wrap
  with `(input, init) => fetch(input, init)`.

### Verified end-to-end

- All five containers green (`api`, `worker`, `postgres`, `redis`,
  `minio`).
- POST `/v1/transcripts` with the real Polish PDF → page-1 PNG → 200
  in ~4s with `claude-sonnet-4-6`, 3,192/419 tokens, $0.0313, real
  19KB xlsx downloadable via `/v1/jobs/<id>/result`.
- Idempotency replay with the same `Idempotency-Key` returns the cached
  body in <1s.
- DSR access surfaces the matching transcript; erasure crypto-shreds
  the row + blobs, leaving `record_count: 0` and the result endpoint
  404ing.
- All UI pages exercised against the running stack via Playwright MCP.
- 503 Python tests + 12 TypeScript tests still green.

## [0.1.0] — 2026-04-25

First MVP release. Polish ŚWIADECTWO SZKOLNE → US High School Grade 9 Excel,
end-to-end, on a schema-driven foundation that scales to any source language /
target system without code changes.

### Added

#### Core domain (Phase 1)
- `CanonicalTranscript` IR + Pydantic v2 strict models for student, conduct,
  subject, grade.
- PII classification system (`PIIClass.PII_DIRECT` / `PII_QUASI` /
  `EDUCATIONAL` / `SENSITIVE`) with regex-based redaction tested across logs.
- Domain exception hierarchy mapping to RFC 7807 problem-detail responses.

#### Profiles + targets + mapping (Phase 2)
- YAML-driven profile/target bundle loaders with override resolver
  (kustomize-style deep merge).
- Polish `pl.lo.swiadectwo_szkolne.v1` profile + US-HS `us-hs.v1` target,
  including grade-scale mapping (Polish 6-point ↔ US A+/A/.../F), subject
  vocabulary translation, and advanced-subject hour bonus computation.
- Mapping engine producing render-data dicts from canonical input.

#### Vision adapters (Phase 3)
- `VisionAdapter` Protocol + `ProviderRouter` with `AdaptivePolicy`,
  `RegionPolicy`, `RoundRobinPolicy`, `FixedPolicy`.
- Anthropic adapter (Haiku-primary, Sonnet-fallback by confidence) with
  prompt caching, structured outputs (`output_config.format`), and a `_meta`
  envelope for confidence + warnings.
- OpenAI / Google / Tesseract scaffold adapters (raise `NotImplementedError`).
- Image preprocessing (EXIF strip via `frombytes(tobytes())`, autocontrast,
  resize to ≤1568px) + PDF→PNG via pdf2image.
- In-memory async result cache.

#### Pipeline engine (Phase 4)
- `Step` Protocol + `PipelineContext` + `PipelineRun` engine.
- Built-in steps: `preprocess`, `detect_profile`, `extract`, `translate`,
  `validate`, `quality_gate`, `human_review`, `map`, `render`,
  `notify_webhook`, `persist`.
- 3 pipelines: `default_v1`, `with_manual_review_v1`, `batch_economy_v1`.
- openpyxl `XlsxRenderer` that preserves template formatting.

#### Persistence (Phase 5)
- SQLAlchemy 2.0 async + Alembic; cross-dialect GUID/JSONB types for
  SQLite-in-tests + Postgres-in-prod.
- Postgres RLS policy script (3-layer tenant isolation: app filter + ORM
  scope + `SET LOCAL app.tenant_id`).
- AES-GCM-256 envelope encryption (per-tenant DEK wrapped by env-KEK;
  HSM/KMS interface scaffolded).
- Argon2id-hashed API keys.
- Hash-chained audit log (SHA-256 of canonical JSON, append-only).
- S3-compatible blob store + local-fs fallback.
- Per-tenant repositories: tenants, api_keys, jobs, transcripts, audit_log,
  usage_records, idempotency_keys, result_cache, webhooks.

#### REST API (Phase 6)
- FastAPI v1 surface: `POST /v1/transcripts`, `GET /v1/jobs/{id}` and
  `/result`, `POST /v1/webhooks` (returns one-time signing secret), `GET
  /v1/webhooks`, `GET /v1/usage`, `GET /v1/templates`.
- Bearer-token auth (Argon2id) + tenant context.
- RFC 7807 `application/problem+json` error envelopes.
- Request-id + security-headers middleware.
- 24-hour idempotency cache for POST endpoints.
- `/health`, `/ready`, `/version` system endpoints.

#### Async + batch + retention (Phase 7)
- Pluggable `Queue` Protocol + in-process `InMemoryQueue` with
  visibility-timeout reclaim and delayed redelivery.
- Anthropic Batch API adapter (50% cheaper economy lane) — submit, poll,
  fetch results.
- `BatchSubmission` table + repo tracking provider batch state across
  worker restarts.
- `WorkerRunner` dispatch loop with exponential-backoff retries; handlers
  for `TRANSCRIPT_JOB`, `BATCH_SUBMIT`, `BATCH_POLL`, `RETENTION_SWEEP`.
- `RetentionService`: walks expired jobs, deletes encrypted transcripts +
  blobs, writes audit log.
- `POST /v1/transcripts:batch` endpoint (up to 100 files per request).

#### SLA tiers + manual review (Phase 8)
- Four SLA tiers (`economy` / `standard` / `premium` / `enterprise`) as YAML
  presets at `sla-tiers/<tier>.yaml`.
- `TenantSlaConfig` (sync allowed, p95 target, provider policy, primary
  model, fallback model, confidence threshold, retention days, audit
  detail, region pin, WORM flag, SIEM flag).
- Sync gate: `POST /v1/transcripts` 403s for tiers with `sync_allowed=False`.
- Confidence gate: low-confidence extractions parked for manual review when
  the tier has `park_low_confidence=True`.
- Manual-review endpoints: `GET /v1/jobs?status=parked`, `POST
  /v1/jobs/{id}/approve` (re-extract with stronger model), `POST
  /v1/jobs/{id}/reject`.

#### SDKs + CLI + MCP (Phase 9)
- Python SDK (`ocr-to-report-sdk-py`): sync + async clients, typed Pydantic
  response models, typed exception hierarchy mapped from problem-detail.
- TypeScript SDK (`@ocr-to-report/sdk`): hand-written, fetch-based, runs in
  Node 20+, browser, Cloudflare Workers, Deno; full strict-mode types.
- Typer CLI (`ocr-to-report`): process, batch, jobs (get/list/approve/
  reject/result), webhooks, usage, templates, version. JSON output by
  default; `--pretty` switches to Rich tables.
- FastMCP server (`ocr-to-report-mcp`): ten tools mirroring the API
  surface for AI agents.

#### Observability (Phase 10)
- Three-tier Prometheus metrics (golden signals, pipeline, business) with
  `/metrics` endpoint.
- ASGI middleware recording per-route request count + latency + 4xx/5xx.
- OpenTelemetry tracing — opt-in via `OCR2R_OTLP_ENDPOINT`,
  ParentBased(TraceIdRatioBased) sampler at 5%, FastAPI + httpx
  auto-instrumentation.
- SLO + operational alert rules (`observability/prometheus_alerts.yaml`):
  availability budget, p95 latency, confidence budget, circuit-open,
  manual-review backlog, webhook failure rate, daily cost cap.
- Importable Grafana dashboard JSON with ten panels.

#### Compliance + hardening (Phase 11)
- GDPR DSR endpoints: `GET /v1/dsr/access` (Article 15), `GET
  /v1/dsr/portability` (Article 20), `POST /v1/dsr/erasure` (Article 17).
  Each appends a FERPA-disclosure-tagged audit-log entry.
- Magic-byte upload validation (`require_safe_upload`) — defense in depth
  against polyglot files; rejects anything that isn't PDF/PNG/JPEG/GIF/
  WebP/TIFF.
- Subject identity in audit log stored as SHA-256 hash, never plain text.

### Repository

- 8 Python packages (uv workspace): core, adapters, api, worker, cli,
  sdk_py, mcp + sibling sdk-ts (pnpm/npm).
- Quality gates: ruff, mypy strict, bandit, pip-audit, pytest, syrupy,
  hypothesis, schemathesis, import-linter.
- 503 tests passing (unit, property, integration, e2e); mypy strict clean
  on 198 source files.
- Layered architecture enforced by import-linter: cli/mcp → worker → api →
  adapters → core; sdk_py never imports server-side code.

### Deferred to v1.1+

- Full implementations of OpenAI/Google/Tesseract vision adapters.
- KMS / HSM integration (interface ready; env-based KEK in MVP).
- Helm chart for Kubernetes.
- Custom Python step plugin loader.
- WORM audit + SIEM export integrations (Premium/Enterprise gating).
- OIDC / SAML SSO.
- Web admin dashboard.
- DOCX / PDF output renderers.
- ML-based auto-fingerprinting (regex-based detection in MVP).

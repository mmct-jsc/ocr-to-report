# Changelog

All notable changes to OCR-to-Report. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), versioning follows [SemVer](https://semver.org/).

## [0.2.1] — 2026-05-21

Security patch release. Fixes two findings surfaced by an internal
security review of the v0.2.0 customization surfaces. **Operators
running v0.2.0 should upgrade.**

### Security

- **(HIGH) Cross-tenant blob read via `templates[<key>].blob_key`
  patch injection.** The `POST /v1/transcripts` render path fetched
  the patch's `value` field verbatim from the blob store; multi-tenant
  storage shares one keyspace (only path prefixes segregate). A
  tenant could `PUT /v1/tenant/config` with a patch pointing at
  another tenant's blob, then run a job and have the renderer return
  the foreign template (or, by varying the key, any job-output blob
  with extracted PII). Fixed with a two-layer guard: write-time
  rejection in `PUT/POST :preview` of any
  `templates[<key>].blob_key` patch whose value doesn't start with
  `tenant/{caller.tenant_id}/templates/`, plus matching read-time
  rejection in `transcripts.py` as defense-in-depth. Even if a row
  leaks past the PUT guard (manual SQL, future schema migration),
  the render path refuses to honor it. New regression tests:
  `test_put_rejects_foreign_tenant_blob_key_patch` +
  `test_preview_rejects_foreign_tenant_blob_key_patch`.

- **(MEDIUM) Unrestricted `pipeline_id` write.** The PUT handler
  wrote `body.pipeline_id` directly to `tenant.pipeline_id` with no
  validation, leaving the pipeline loader to reject unknown ids at
  job time. A path-traversal payload like `../../etc/passwd` would
  land in the DB and only be filtered downstream — whether that
  becomes a real file read depends on the loader's path handling.
  Now `_list_shipped_pipelines` enumerates the available `*.yaml`
  files under `pipelines_root` and the PUT/`:preview` validator
  rejects any id not in that set with HTTP 400. Path-traversal
  payloads die at the API gate. Regression test:
  `test_put_rejects_unknown_pipeline_id`.

### Internal

- Hardening passes that landed alongside v0.2.0 but didn't justify a
  release on their own: axe-core static a11y audit of the new
  Settings tabs (5 issues fixed including a missing tablist
  `aria-label`), schemathesis-driven contract tests covering all four
  v0.2.0 endpoints under the `contract` pytest marker, and 6 bugs
  caught by the code-reviewer agent (silent `pipeline_id` no-op when
  `session.get(Tenant, …)` returns None, `get_resolved_tenant_config`
  opening a second DB session per request, DELETE returning 204 for
  a missing template_key on an existing target_id row, and three
  smaller UI fixes).

No new endpoints, schema migrations, or breaking changes.

## [0.2.0] — 2026-05-21

The "fully customizable per tenant" milestone. Every tenant now picks
their own pipeline, tunes SLA fields above the tier preset, uploads
their own xlsx templates, and edits raw profile-vocabulary patches —
all through the Settings page, all without code changes. None of this
is a fork of the engine; it's the override resolver shipped in v0.1.0
finally wired through the request path, exposed via REST, mirrored in
both SDKs, and surfaced in the web console.

### Added

- **`/v1/tenant/config` CRUD.** `GET` returns the resolved view (tier
  preset with SLA patches applied) plus the raw patch lists per scope.
  `POST /v1/tenant/config:preview` applies the same body without
  persisting — the diff editor in the console uses it for live
  "what would saving do?" previews. `PUT /v1/tenant/config` writes
  per-scope replace-semantic; SLA patches dry-run through strict
  Pydantic re-validation before persistence, so an out-of-range
  threshold is rejected with a 400 instead of producing a corrupt
  row. Direct `pipeline_id` writes ride this endpoint too.

- **`POST /v1/templates/{target_id}/{template_key}` xlsx upload.**
  Multipart `template_file`. Three-stage validation: ZIP magic bytes,
  then `openpyxl.load_workbook` round-trip, then storage at
  `tenant/{tenant_id}/templates/{target_id}/{template_key}/<sha256>.xlsx`.
  Writes the override row by **merging** the new
  `templates[<key>].blob_key` patch into any existing target-scope row
  so co-located vocabulary patches survive. `DELETE` reverts to the
  shipped template (best-effort blob cleanup).

- **Override resolver wired into the request path.** New
  `ResolvedTenantConfig` dataclass + `get_resolved_tenant_config`
  per-request dependency in `api.deps`. Memoized on `request.state` so
  multiple deps in the same request share a single DB read. The
  transcripts router consumes `get_current_sla` (resolved) instead of
  `resolve_sla_for_tenant` (un-patched), so tenant overrides actually
  influence live jobs.

- **Postgres integration workflow.** `.github/workflows/integration.yml`
  spins up postgres 16 + redis 7 service containers and runs the
  `@pytest.mark.integration` slice on every push to `main` and every
  PR. The flagship test (`test_v0_2_0_integration.py`) walks the full
  customization stack against real postgres: SLA patch + pipeline
  switch + target override + custom template upload in one PUT, then
  a transcript job whose rendered xlsx carries the uploaded
  template's watermark. Catches dialect drift (JSONB column types,
  the `SET LOCAL app.tenant_id` GUC) that the sqlite unit suite can't.

- **SDK exposure (TS + Py).** Both clients gain `TenantConfigResource`
  (`get`/`preview`/`replace`) and an extended `TemplatesResource` with
  `upload(...)` + `delete(...)`. Public types: `OverridePatch`,
  `TenantConfigUpdate`, `TenantConfigResponse`,
  `CustomTemplateResponse`. URL components are `encodeURIComponent`'d
  so target_ids with slashes or spaces survive path composition.

- **Web Settings — 5 tabs.** General (the existing connection /
  appearance cards), Pipeline (radio list of shipped pipelines with
  summaries), SLA (per-field override toggles for
  `confidence_threshold`, `park_low_confidence`, `retention_days`,
  `provider_policy`), Templates (drag-and-drop xlsx upload per
  `(target_id, template_key)` slot), Vocabulary (raw JSON-patch
  editor for `profile_overrides`). New `Tabs` primitive
  (`web/src/components/ui/tabs.tsx`) — full WAI-ARIA "tabs" pattern,
  keyboard nav (Arrow/Home/End), roving tabindex; hand-rolled, no
  Radix.

- **First alembic migrations.** `migrations/versions/0001_baseline.py`
  baselines the 10 shipped tables; `0002_tenant_overrides.py` adds the
  `tenant_overrides` table + its `(tenant_id, scope, target_id)`
  unique constraint. Cross-dialect (sqlite + postgres) shapes; CI
  runs `alembic upgrade head` against postgres on every push.

- **Ops hardening alongside v0.2.0.** Release smoke job now pulls +
  cosign-verifies all three published images (api, worker, web) and
  curls the web image's `/` to confirm nginx actually serves 200.
  Non-gating `Trivy scan (MEDIUM, informational)` step gives
  visibility on incoming risks without flapping the gate. Every
  workflow opts into Node 24 ahead of the June 2026 default flip via
  `FORCE_JAVASCRIPT_ACTIONS_TO_NODE24`.

### Changed

- **`resolve_sla_for_tenant` is now the un-patched-baseline accessor.**
  Code paths that consumed it directly (the transcripts router)
  switched to `get_current_sla` so they get the resolved view. The
  old function stays as the explicit "give me the tier preset before
  overrides" door — useful for diff-preview shapes.

- **Multi-arch web image builds natively, not under emulation.** The
  Vite/TS build stage now uses `FROM --platform=$BUILDPLATFORM` so the
  builder runs on the host arch once; the resulting static bundle is
  copied into both per-arch `nginx:1.27-alpine` runtimes. Cut the
  release web build from a 30-min qemu stall to ~90 seconds.

### Migration notes

- No database migrations land automatically on boot. Operators run
  `alembic upgrade head` (or set `OCR2R_AUTO_MIGRATE_ON_BOOT=true` for
  development). The schema added in this release is additive — no
  existing tables changed.

- API key holders without any patch rows see identical behavior to
  v0.1.0; the resolver short-circuits on the empty-patches path. The
  `pipeline_id` column already existed on `tenants`; v0.2.0 just
  exposes a write surface for it.

- TS SDK callers using `client.templates.list()` are unaffected; the
  new `upload`/`delete` methods are additive. Python SDK callers
  importing from `ocr_to_report.sdk_py` gain `TenantConfigResponse`,
  `TenantConfigUpdate`, `CustomTemplateResponse` types — no existing
  imports moved.

## [0.1.0+resilience] — 2026-05-20

Defense-in-depth for the empty-volume-silently-500s failure mode. After a
`docker compose down -v` (or any other path that wipes
`ocr2r_postgres_data`), every authenticated endpoint hit
`UndefinedTableError: relation "api_keys" does not exist` inside
`authenticate()` and returned an opaque 500 — `/v1/health` kept returning
200 the whole time because it doesn't touch the DB, so observers
debugged the wrong endpoint. Three independent improvements:

### Added

- **`/v1/ready` deep database check.** The readiness endpoint now probes
  the schema by running `SELECT 1 FROM api_keys LIMIT 0`. Returns:
  - `{"status": "ok", "checks": {"database": "ready", ...}}` with **200** when the schema is in place,
  - `{"status": "degraded", "checks": {"database": "schema_missing", ...}}` with **503** when the DB is reachable but tables are gone,
  - `{"status": "degraded", "checks": {"database": "unreachable", ...}}` with **503** when the connection itself fails.

  Kubernetes `readinessProbe` and the web SPA's health pulse both
  surface the actual issue. **Breaking-shaped change** for anyone who
  treated `/v1/ready` as always-200 — that was never the contract; the
  endpoint now reflects reality.

- **`OCR2R_AUTO_MIGRATE_ON_BOOT` setting** (default **off**, dev/CI
  convenience). When true, the API lifespan runs `Base.metadata.create_all`
  on startup so a fresh database volume self-heals to a working schema
  without an out-of-band `ocr-to-report bootstrap` run. Compose now
  ships with this on so local dev never hits the empty-volume trap.
  Production deploys must keep it off; schema changes belong in alembic
  (arriving in v0.2.0, Task 1 of `docs/plans/2026-04-29-v0.2.0-...`).

- **`docs/runbooks/empty-database-recovery.md`** — first entry in the
  previously-empty runbooks directory. Diagnoses the symptom, lists
  three recovery paths (auto-migrate env var, host bootstrap CLI,
  container-side bootstrap CLI), covers the `cut -d= -f2-` gotcha that
  eats the trailing `=` of the base64 KEK, and documents the
  prevention story for dev vs. production.

### Tests

- 4 new tests in `packages/api/tests/test_readiness_and_automigrate.py`:
  empty schema → 503 with `schema_missing`; present schema → 200 with
  `ready`; auto-migrate disabled by default; auto-migrate enabled
  creates schema during lifespan.
- 1 existing test in `test_health.py` updated — was pinning
  `/v1/ready` to always-200, now correctly asserts the 200-or-503
  contract plus `checks.database` membership.

Totals: 62 Python + 15 TypeScript tests passing.

## [0.1.0+cors] — 2026-04-29

### Fixed

- **Cross-origin browser callers got `405 Method Not Allowed` on every
  authenticated request.** The API has no CORS middleware, so the
  ``OPTIONS`` preflight that browsers send before any non-simple request
  (anything with `Authorization: Bearer …`) hit the FastAPI router with
  no matching handler and was rejected with 405. Same-origin deployments
  (web nginx proxies `/api/*` to the API) were unaffected, but the
  moment the API was exposed on a different origin — most obviously when
  shared through a separate Cloudflare tunnel from the web console —
  every SDK-driven page broke.

### Added

- `OCR2R_CORS_ALLOWED_ORIGINS` (list) and
  `OCR2R_CORS_ALLOWED_ORIGIN_REGEX` (string) settings. Both default to
  empty / null, preserving the previous "same-origin only" posture; the
  CORS middleware is only installed when at least one is set. Headers
  allowed on cross-origin requests: `Authorization`, `Content-Type`,
  `Idempotency-Key`, `X-Acting-Tenant-Id`, `X-Request-Id`. Methods:
  `GET`, `POST`, `PUT`, `PATCH`, `DELETE`, `OPTIONS`. Preflight cached
  for 10 minutes (`max_age=600`).
- `docker-compose.yml` now seeds
  `OCR2R_CORS_ALLOWED_ORIGIN_REGEX=https://.*\.trycloudflare\.com` so a
  tunneled web on one quick-tunnel hostname can call a tunneled API on
  another out of the box. Operators override via `.env` for production.
- 5 new tests (`packages/api/tests/test_cors.py`) covering: default
  locked-down posture preserved, allowlist preflight succeeds, regex
  preflight succeeds, untrusted origin rejected, real GET responses
  carry `Access-Control-Allow-Origin`.

Totals: 58 Python + 15 TypeScript tests passing.

## [0.1.0+admin] — 2026-04-26

Admin section + cross-tenant viewing for support and ops. Builds on
`0.1.0+ui`; same containers, additive only.

### Added

- **Admin section in the API** (`/v1/admin/*`, gated on the `admin:*`
  scope) — system overview, tenant CRUD with SLA tier + archival,
  per-tenant API-key issuance + revocation, and a paged audit log.
  `bootstrap --admin` mints the first admin key.
- **Admin pages in the Web Console** — System (KPIs + bundle inventory
  + queue depth), Tenants (table view, create dialog, archive),
  Tenant detail (API keys, audit log).
- **Tenant impersonation via `X-Acting-Tenant-Id`** — admin keys can
  view *any* tenant's data on the regular tenant-scoped pages
  (Dashboard, Jobs, Webhooks, Compliance, Templates, Settings) by
  setting the header. The TS SDK exposes it as the `actingTenantId`
  client option + `setActingTenantId()` setter; the web UI surfaces
  it as a topbar **TenantSwitcher** dropdown that triggers a
  `react-query` invalidation so every visible page refetches under
  the new tenant context. Non-admin keys that try to impersonate get
  403; admins pointing at an unknown tenant get 404.
- **Impersonation auditing** — every successful impersonation appends
  a `tenant.impersonated_access` row on the **target** tenant (so its
  auditors can see who accessed their data and when). The metadata
  records the admin's home tenant, the HTTP method, and the path.

### Fixed

- **Starlette `MultiPartParser.max_part_size`** defaulted to 1 MiB,
  silently truncating real multi-page PDF uploads (5–20 MB rendered).
  Now wired to `settings.max_upload_bytes` so the request reaches the
  upload guard instead of dying at the parser.
- **PDF render latency** — single-thread `pdf2image` at 200 DPI
  blocked the lone uvicorn worker for 25+ seconds per page on the
  benchmark transcript. Drop to 150 DPI + `thread_count=2` and run
  with `OCR2R_API_WORKERS=2` in `docker-compose.yml`. Two-page PDF
  now finishes in ~117s end-to-end with the full grade list (was
  template-only because page 2 never reached the model).

### Tests

- **5 new Python tests** (`test_phase12_tenant_impersonation.py`):
  admin can swap, non-admin gets 403, unknown UUID gets 404, invalid
  UUID gets 403, and audit row lands on the target tenant.
- **3 new TS SDK tests**: header sent when set, omitted when unset,
  cleared on `setActingTenantId(null)`.

Totals: 53 Python + 15 TypeScript tests passing.

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

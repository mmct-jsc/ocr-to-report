# OCR-to-Report — System Design & Implementation Plan

| Item | Value |
|---|---|
| Date | 2026-04-25 |
| Owner | QuocTran |
| Repo | `D:\Repository\OCR_to_Report_QT` |
| Status | Plan finalized; awaiting go-ahead for Phase 0 |
| Target MVP | v0.1.0 — end of Phase 11 |

---

## 1. Problem Statement

Convert school transcripts (initially Polish ŚWIADECTWO SZKOLNE; ultimately any
language and education system) into target-system reports (initially a US High
School Grade 9 Excel template; ultimately any tabular/document target).

The system must:

- Be **exposable as a plugin** to external systems via REST, Python SDK,
  TypeScript SDK, CLI, and MCP — same operations through every surface.
- Support **multiple AI/OCR providers** behind a pluggable adapter interface
  (Anthropic, OpenAI, Google, Tesseract).
- Support **all source languages and target systems** through a schema-driven
  profile + target bundle architecture.
- Be **fully configurable per tenant** — workflow pipelines, SLA tier, retention,
  region, encryption, manual review, custom templates.
- Meet **strict coding, security, and logic constraints**: type-safe end-to-end,
  PII-aware, FERPA + GDPR aligned, defense-in-depth.
- Be **cost-effective for business** at SaaS scale — tiered Claude vision with
  prompt caching, image preprocessing, and result caching.

---

## 2. Locked Design Decisions

### Decision 1 — Tiered Vision Pipeline (multi-provider)

Pluggable `VisionAdapter` protocol. Built-in providers:

| Provider | Default tier |
|---|---|
| Anthropic Claude (Haiku 4.5 primary, Sonnet 4.6 fallback) | Default; prompt caching enabled |
| OpenAI (gpt-4o-mini / gpt-4o) | Optional drop-in |
| Google (Gemini 2.x Flash / Pro via Vertex) | Optional, EU/Asia compliance |
| Tesseract | Optional, air-gapped/on-prem |

Routing policies: `Adaptive` (cheapest first → confidence-gated fallback),
`Fixed`, `RoundRobin`, `Region`. Image preprocessing (Pillow: EXIF strip,
deskew, autocontrast, resize ≤1568px). Result cache keyed by
`sha256(preprocessed_image) || provider_id || schema_version`.

Cost (blended, with caching, adaptive policy):
~$3.40 per 1000 transcripts real-time; ~$1.50 per 1000 batch.

### Decision 2 — Architecture & Deployment Topology

- Hexagonal layered architecture (core → adapters → entrypoints).
- **Stateless API workers** + **Arq + Redis** queue for async batch lane.
- **PostgreSQL** primary store with Row Level Security per tenant.
- **S3-compatible blob store** (MinIO local/dev, S3/R2/GCS prod).
- **Docker Compose** for MVP deployment; Helm chart deferred to v1.1.
- 12-factor config via `pydantic-settings`; secrets in env, KMS-ready.

### Decision 3 — Public Integration Surfaces (the "plugin" contract)

Four surfaces, all backed by the same core:

1. **REST API** (FastAPI, OpenAPI 3.1) — versioned `/v1/...`, RFC 7807 errors,
   `Idempotency-Key` headers, HMAC-signed webhooks.
2. **Python SDK** (`pip install ocr-to-report`) — sync + async HTTP client +
   re-export of `core` for in-process use.
3. **TypeScript SDK** (`@ocr-to-report/sdk`) — generated from OpenAPI, hand-
   written wrappers; published to npm.
4. **CLI** (Typer) — `ocr-to-report process …`, `batch …`, `templates …`.
5. **MCP server** (FastMCP) — same operations as MCP tools for AI agents.

Endpoints (MVP): `POST /v1/transcripts`, `POST /v1/transcripts:batch`,
`GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/result`, `GET/POST /v1/templates`,
`POST /v1/webhooks`, `GET /v1/usage`, `GET /v1/health`, `/ready`, `/version`,
plus tenant config + pipeline endpoints (Decisions 5, 8).

### Decision 4 — Schema-Driven Five-Axis Universal Model

```
SOURCE PROFILE   →   CANONICAL TRANSCRIPT   →   TARGET SYSTEM   →   OUTPUT TEMPLATE
(YAML bundle)        (language-neutral IR)      (YAML bundle)       (xlsx/pdf/csv)
                          ↑      ↓
                    MAPPING RULES
                 (vocab, grade, year, hours)
```

- **Source profile bundles**: `profiles/<id>/{manifest,extraction_schema,
  vocabulary,grade_scale,year_system,prompts/,samples/}` (YAML).
- **Target system bundles**: `targets/<id>/{manifest,grade_scale,year_system,
  subject_taxonomy,templates/}`.
- **Canonical IR**: `CanonicalTranscript` Pydantic model with normalized
  grades (0..1 + 6-level categorical), ISCED-aligned subject IDs, conduct,
  achievements. Round-trips losslessly with `raw_source_value`.
- **Per-tenant overrides**: deep-merge JSONB patches (kustomize-style) on any
  bundle path — vocabulary, taxonomy, custom xlsx templates, etc.
- **Pydantic invariants** structurally enforce: hour math, grade derivation,
  year derivation, confidence monotonicity.

Database schema: 14 tables (tenants, api_keys, users, webhooks, profile_versions,
target_versions, tenant_overrides, templates, jobs, transcripts, audit_log,
usage_records, idempotency_keys, result_cache). All `tenant_id`-scoped, RLS
policies enforced at DB layer. PII columns AEAD-encrypted with per-tenant DEK.

**MVP content**: Polish `pl.lo.swiadectwo_szkolne.v1` + US-HS `us-hs.v1`
Grade 9 fully built. Scaffolding for vi/es/de/fr/en + us-college/uk-ucas/ib-dp +
Grade 10/11/12 (YAML stubs with TODO markers).

### Decision 5 — SLA Tiers + Workflow Engine

**Pipelines = ordered Steps** declared in YAML. Step protocol:

```python
class Step(Protocol):
    id: str
    async def run(self, ctx: PipelineContext) -> StepResult: ...
```

Built-in steps (MVP): `preprocess`, `detect_profile`, `extract`, `translate`,
`validate`, `quality_gate`, `human_review`, `map`, `render`, `persist`,
`notify_webhook`. Steps add immutable artifacts to `PipelineContext`; pipelines
are fully traceable and replayable from any point.

**Pipelines shipped**: `default_v1`, `with_manual_review_v1`, `batch_economy_v1`.
Tenants pick or define custom pipelines via `POST /v1/pipelines`.

**SLA tiers**: `economy` / `standard` / `premium` / `enterprise`. Each is a
YAML preset filling `TenantSlaConfig` (latency target, provider mix, confidence
threshold, concurrency, rate limit, retention, region, encryption strategy,
audit detail, manual review queue, webhook reliability, SLO credits).

Per-field SLA overrides supported. Custom Python step plugins deferred to
post-MVP (protocol stable from day 1).

### Decision 6 — Security & Compliance

Defense-in-depth (L1 host → L7 app):

- **Auth**: API keys (Argon2id hashed, prefix-visible), optional JWT (ES256,
  rotating JWKS), scope-based RBAC (`viewer`/`processor`/`reviewer`/`admin`/
  `owner`).
- **Tenant isolation**: app filter + ORM `SET LOCAL` + Postgres RLS (3 layers).
- **Encryption**: envelope encryption per-tenant DEK + env-based KEK (KMS-ready
  interface); AES-GCM column AEAD. Crypto-shredding on tenant deletion.
- **PII annotations**: `PIIClass` enum on every field (DIRECT, QUASI,
  EDUCATIONAL, SENSITIVE) drives auto-redaction in logs, webhook payloads,
  audit metadata.
- **Religion/ethics field**: GDPR Art. 9 — excluded by default, opt-in only
  with documented basis, separate DEK, 30-day hard cap.
- **Input hardening**: magic-byte check, 25MB / 10-page limits, EXIF strip,
  Pillow re-encoding, Pydantic strict.
- **Rate limit + idempotency**: Redis token bucket + 24h-cached replay.
- **Audit log**: hash-chained append-only, FERPA disclosure log included.
  Standard tier: Postgres only. Premium: + WORM. Enterprise: + SIEM.
- **Egress allowlist**: Docker network policy restricts worker outbound to
  provider APIs + tenant-registered webhook URLs.
- **Compliance positioning**: FERPA + GDPR aligned in MVP; SOC 2 readiness
  post-MVP.

### Decision 7 — Testing & Observability

**Test pyramid**:
- ~400 unit, ~150 property (`hypothesis`), ~80 integration (`testcontainers`),
  contract (`schemathesis`), ~10 E2E nightly (live providers, $5/day cap),
  snapshot (`syrupy`) for Excel + JSON outputs, mutation (`mutmut`) on
  `core/translate.py` + `core/validate.py`.
- Targets: ≥90% coverage `core/`, ≥80% overall, 100% `mypy --strict`, suite
  <60s locally.
- **No real student data in repo**. Three fixture tiers: synthetic, anonymized,
  cassettes (`pytest-recording`).

**Observability** (OpenTelemetry-native):
- **Logs**: `structlog` JSON with auto-PII-redaction.
- **Metrics**: Prometheus `/metrics`. Tier 1 (golden signals), Tier 2 (pipeline:
  step duration, confidence histogram, tokens, $cost, circuit state), Tier 3
  (business: transcripts/tenant/profile/target/sla, manual_reviews_pending,
  webhook delivery, cache hits).
- **Traces**: OTLP, 5% sample / 100% errors, `gen_ai.*` attributes on provider
  spans.
- **SLOs as code**: Prometheus alert rules shipped in repo.
- **Endpoints**: `/health`, `/ready` (deep), `/version` (build SHA + bundle
  versions).

**CI gates**: ruff, mypy --strict, bandit, semgrep, pip-audit, pytest, coverage,
schemathesis, snapshots, trivy, CycloneDX SBOM. Nightly: live E2E + load test +
mutation sample.

### Decision 8 — Repo Layout + Build Sequence

Multi-package Python monorepo (uv workspace) + sibling TypeScript SDK (pnpm).
Dependency direction enforced by `import-linter` rule:

```
core ← adapters ← api ← worker ← cli, mcp
                         ↖ sdk_py (HTTP only; never imports api)
```

**Repo top level**:

```
ocr-to-report/
├── packages/{core, adapters, api, worker, cli, sdk_py, mcp}/
├── sdk-ts/
├── profiles/<id>/{manifest, extraction_schema, vocabulary, grade_scale,
│                  year_system, prompts/, samples/}/...
├── targets/<id>/{manifest, grade_scale, year_system, subject_taxonomy,
│                templates/}/...
├── pipelines/{default_v1, with_manual_review_v1, batch_economy_v1}.yaml
├── sla-tiers/{economy, standard, premium, enterprise}.yaml
├── migrations/                   # Alembic
├── docker/{api,worker}.Dockerfile
├── deploy/compose/  deploy/helm/  (helm post-MVP)
├── tests/{fixtures, unit, property, integration, contract, e2e, load,
│         snapshots, cassettes}/
└── docs/{plans, runbooks, adr}/
```

---

## 3. Twelve-Phase Build Sequence

Each phase is self-contained, demoable, leaves CI green, leaves trunk releasable.
**Definition of Done per phase**: tests pass, coverage met, mypy strict clean,
all security scans clean, docs updated, demoable command produces expected
output.

| # | Phase | Demoable artifact |
|---|---|---|
| 0 | Bootstrap | `make dev` brings up empty stack; `curl /health` → 200; CI passes |
| 1 | Core domain types + PII + redaction | `pytest packages/core` 200+ tests pass; mypy strict clean |
| 2 | Profiles + targets + mapping engine + Polish + US-HS Grade 9 | YAML-driven Polish→US-HS mapping snapshot test passes |
| 3 | Vision adapters + image pipeline + result cache (Anthropic full) | `python -m ...adapters.vision` on anonymized fixture → valid `CanonicalTranscript` |
| 4 | Pipeline engine + steps + openpyxl Excel renderer + `default_v1` | CLI: `process sample.pdf` → snapshot-matching `output.xlsx` |
| 5 | Persistence: Postgres + RLS + envelope encryption + blob + audit chain | Integration tests pass; manual SQL injection cannot cross tenants |
| 6 | REST API: auth, rate limit, idempotency, endpoints, webhooks, OpenAPI | `curl POST /v1/transcripts -F file=@…` returns extraction + Excel; webhook fires |
| 7 | Async worker + Arq queue + Anthropic Batch API + retention cron | `POST /v1/transcripts:batch` of 50 PDFs completes overnight at half cost |
| 8 | SLA tiers + tenant config + custom pipelines + manual review | Premium tenant 0.95 threshold parks low-confidence job; reviewer approves; render |
| 9 | SDKs (Py + TS) + CLI + MCP server | All four surfaces produce identical output for the same input |
| 10 | Observability: OTel, Prometheus, SLOs, alerts, Grafana dashboard | Dashboard shows per-tenant cost/latency/error/confidence; SLO breach alerts |
| 11 | Compliance + hardening + v0.1.0 release | All scans clean; SBOM; signed images; GDPR DSRs working; FERPA log live |

**Parallelization (post-Phase 2)**:
- Track A: 3 → 4 → 7 (vision/pipeline/worker)
- Track B: 5 → 6 → 8 (DB/API/SLA)
- Track C: 9 (SDKs/CLI/MCP) once Phase 6 frozen
- Track D: 10 (instrumentation throughout, formalized at end)
- Phase 11: integration/polish, sequential.

---

## 4. MVP Scope Freeze

**Included in MVP (v0.1.0)**:

- Polish ŚWIADECTWO SZKOLNE → US-HS Grade 9 Excel, fully working end-to-end.
- Schema-driven profile/target/pipeline/SLA universal foundation.
- Scaffolds for: vi, es, de, fr, en source profiles; us-college, uk-ucas, ib-dp
  targets; Grade 10/11/12 templates. Adding any of these = fill YAML, no code.
- Vision adapters: Anthropic fully implemented; OpenAI/Google/Tesseract have
  interface tests + scaffolds (stubs raise `NotImplementedError` with clear
  message).
- All four integration surfaces (REST + Python SDK + TS SDK + CLI + MCP).
- 3 pipelines + 4 SLA tiers + custom pipeline upload + per-field SLA overrides.
- Multi-tenant + envelope encryption + hash-chained audit + GDPR DSRs +
  FERPA disclosure log.
- Full observability stack + SLO alerts.
- Docker Compose deployment + 1 demo tenant seed.

**Deferred to v1.1+**:

- Full implementations of OpenAI/Google/Tesseract adapters.
- Full implementations of additional profile/target bundles.
- Helm chart for K8s.
- KMS / HSM integration (interface ready, env-based KEK in MVP).
- Custom Python step plugins (loader deferred; protocol stable).
- WORM audit + SIEM export (Premium/Enterprise gating).
- OIDC / SAML SSO.
- Web admin dashboard.
- DOCX / PDF output renderers (XLSX only in MVP).
- ML-based auto-fingerprinting (regex-based detection in MVP).

---

## 5. Risk Register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Provider schema drift breaks extraction | Medium | High | Cassette tests + nightly live tests + circuit breaker; pin provider model versions |
| LLM hallucinates grades/names | Low | Critical | Confidence gate; manual review tier; round-trip property tests; snapshot diffs |
| PII leak via logs / webhooks / errors | Low | Critical | PIIClass annotation system; redaction tests verify by regex; CI gate |
| Cross-tenant data leak | Very Low | Critical | 3-layer isolation (app + ORM + RLS); regression test attempts SQL injection |
| Cost overrun on Vision API | Low | Medium | Per-tenant token quotas; budget caps; Haiku tiered + caching; batch lane |
| Polish profile inaccurate on edge cases | Medium | Medium | Property tests covering all 6 grades × 4 classes × variations; staging UAT |
| Storage costs balloon | Low | Low | 7-day default TTL on blobs; lifecycle policy; tenant configurable |
| Audit chain corruption | Very Low | High | Daily cron verifies chain; alert on break; backups |

---

## 6. Open Questions / Future Decisions

These are explicitly **out of scope** for the MVP design but tracked for v1.1+:

- **Pricing model**: per-transcript, per-token, per-seat, or hybrid?
- **Provider failover SLA**: minimum guaranteed availability when primary
  provider is down?
- **Multi-page transcripts**: how to chunk + reassemble? (current MVP assumes
  ≤10 pages, single document.)
- **Handwritten free-text fields**: e.g., "Special achievements" — extract
  verbatim or skip?
- **School verification**: should we verify the school exists in a registry?
  (Out of MVP scope.)

---

## 7. Plan Sign-Off

This document captures all design decisions confirmed up to and including
2026-04-25. Any change to a numbered Decision requires:

1. An ADR (`docs/adr/NNNN-<title>.md`) explaining what changed and why.
2. An update to this document referencing the ADR.
3. Re-confirmation by the owner.

**Owner**: QuocTran
**Status**: Plan finalized; awaiting `proceed` signal to begin Phase 0 (Bootstrap).

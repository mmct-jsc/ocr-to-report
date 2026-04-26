# Architecture

This document describes the runtime topology, module boundaries, and key
patterns. For locked design decisions and phased build sequence, see
[`docs/plans/2026-04-25-ocr-to-report-design.md`](docs/plans/2026-04-25-ocr-to-report-design.md).

## Runtime topology

```
┌──────────────────────────────────────────────────────────────────┐
│  Edge: API Gateway / TLS termination (caller-supplied)           │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│  api (FastAPI workers)                                           │
│   auth · tenant_ctx · rate_limit · idempotency · routes          │
└──────┬──────────────────────────────────────────────┬────────────┘
       │ sync path                          async path│
       │                                              │
       ▼                                              ▼
┌──────────────┐                         ┌────────────────────────┐
│ core         │ ◄──────────────────────►│ Redis queue (Arq)      │
│  domain,     │                         └─────────┬──────────────┘
│  pipelines,  │                                   │
│  mappings    │                                   ▼
└──────┬───────┘                         ┌────────────────────────┐
       │                                 │ worker (Arq workers)   │
       ▼                                 └─────────┬──────────────┘
       └──────────────┬────────────────────────────┘
                      │
       ┌──────────────┼──────────────────────────────┐
       ▼              ▼                              ▼
┌────────────┐  ┌─────────────┐              ┌──────────────────┐
│ PostgreSQL │  │ S3 / MinIO  │              │ Vision Providers │
│ + RLS      │  │ blob store  │              │ (multi-provider  │
│ + envelope │  │ (TTL 7d)    │              │  adapter pool)   │
│  encryption│  │             │              │                  │
└────────────┘  └─────────────┘              └──────────────────┘
```

## Module boundaries

| Package | Responsibility | Allowed imports |
|---|---|---|
| `core` | Pure domain: types, profiles/targets, mappings, pipeline engine, render. **No I/O.** | stdlib + pydantic + structlog |
| `adapters` | Concrete I/O: vision providers, blob, queue, DB | `core`, third-party I/O libs |
| `api` | FastAPI HTTP server | `core`, `adapters` |
| `worker` | Arq async worker | `core`, `adapters` |
| `cli` | Typer CLI | `core`, `adapters`, `sdk_py` |
| `sdk_py` | Public SDK — HTTP client + core re-export | `core` only (never `api`/`adapters`) |
| `mcp` | MCP server | `core`, `sdk_py` |

Direction enforced by `import-linter` (`pyproject.toml > tool.importlinter`)
and gated in CI.

## Five-axis data model

Every transcript task is fully described by 5 orthogonal axes:

```
SOURCE PROFILE  →  CANONICAL IR  →  MAPPING RULES  →  TARGET SYSTEM  →  OUTPUT TEMPLATE
(YAML bundle)      (lang-neutral)    (vocab/grade/      (YAML bundle)     (xlsx/pdf/csv)
                                      year/hours)
```

Adding a new source language = drop a YAML bundle in `profiles/`. Adding a
new target system = drop a YAML bundle in `targets/`. **No core code changes.**

## Workflow engine

Pipelines are ordered Steps declared in YAML (`pipelines/*.yaml`). Each Step
implements:

```python
class Step(Protocol):
    id: str
    async def run(self, ctx: PipelineContext) -> StepResult: ...
```

Built-in steps: `preprocess`, `detect_profile`, `extract`, `translate`,
`validate`, `quality_gate`, `human_review`, `map`, `render`, `persist`,
`notify_webhook`. Steps add immutable artifacts to `PipelineContext`;
pipelines are fully traceable and replayable.

## SLA tiers

Four shipped: `economy`, `standard`, `premium`, `enterprise`. Each is a YAML
preset filling `TenantSlaConfig`. Tenants pick a tier and may override
individual fields. Tier dimensions: latency target, provider mix, confidence
threshold, concurrency, rate limit, retention, region, encryption strategy,
audit detail, manual review queue, webhook reliability.

## Multi-tenancy

Three layers of isolation, defense-in-depth:

1. **App layer** — every query filtered by `tenant_id` from auth context.
2. **ORM layer** — SQLAlchemy session bound via `SET LOCAL app.tenant_id`.
3. **DB layer** — Postgres Row Level Security policies. A SQL-injection bug
   cannot cross tenants.

PII is encrypted column-by-column with a per-tenant DEK (envelope encrypted
by an env-supplied KEK; KMS-ready interface). Tenant deletion =
crypto-shredding.

## Audit log

Hash-chained append-only log per tenant. Each row contains the SHA-256 of
the prior row's canonical JSON. A daily cron verifies the chain. Standard
tier writes to Postgres only; Premium adds WORM (S3 Object Lock); Enterprise
adds SIEM export.

## Observability

OpenTelemetry-native (vendor-neutral):

- **Logs** — `structlog` JSON, PII-redacted via field annotations.
- **Metrics** — Prometheus `/metrics`, three tiers: golden signals, pipeline,
  business.
- **Traces** — OTLP, 5% sampling / 100% on errors, `gen_ai.*` attributes on
  provider spans.
- **SLOs as code** — Prometheus alert rules in repo.

## Deployment

Phase 0 ships `docker-compose.yml` for local dev. Production deployments are
caller-supplied — the same images run on K8s, ECS, Fly.io, Cloud Run, Nomad,
or bare Docker. Helm chart deferred to v1.1.

## Where to read next

- The full design plan: [`docs/plans/2026-04-25-ocr-to-report-design.md`](docs/plans/2026-04-25-ocr-to-report-design.md)
  (locked decisions + MVP build sequence)
- The product roadmap: [`docs/ROADMAP.md`](docs/ROADMAP.md) (post-MVP version
  trajectory — per-tenant overrides, BYOK, subscriptions, i18n, GA)
- Security model: [`SECURITY.md`](SECURITY.md)
- Contributing: [`CONTRIBUTING.md`](CONTRIBUTING.md)
- ADRs: `docs/adr/` (added as decisions are revised)

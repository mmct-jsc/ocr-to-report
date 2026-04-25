# ADR-0001: Initial system design

| Date | 2026-04-25 |
|---|---|
| Status | Accepted |
| Supersedes | — |
| Superseded by | — |

## Context

Project scope (per request): a SaaS platform converting school transcripts
(initially Polish, ultimately any language) into target-system reports
(initially US-HS Grade 9 Excel, ultimately any target). External systems
must integrate as plugins. Strict coding/security/logic constraints. MVP
must scale to full SaaS without rewrite.

## Decision

Eight design decisions, captured in full in
[`docs/plans/2026-04-25-ocr-to-report-design.md`](../plans/2026-04-25-ocr-to-report-design.md):

1. Tiered pluggable vision pipeline — Anthropic Haiku 4.5 primary + Sonnet
   4.6 fallback, prompt caching, multi-provider adapter (OpenAI, Google,
   Tesseract).
2. Hexagonal architecture, FastAPI + Arq + PostgreSQL + S3-compatible blob,
   Docker Compose deployment.
3. Five integration surfaces (REST + Python SDK + TypeScript SDK + CLI +
   MCP), all backed by the same `core`.
4. Schema-driven five-axis universal model: Source Profile → Canonical IR →
   Mapping Rules → Target System → Output Template. YAML bundles for
   profiles and targets.
5. Workflow engine of YAML-declared pipelines composed of Steps; four SLA
   tiers (economy/standard/premium/enterprise) with per-field overrides.
6. Defense-in-depth security: Argon2id API keys, 3-layer tenant isolation
   (app + ORM + Postgres RLS), envelope encryption with per-tenant DEK,
   PII-class annotations driving auto-redaction, hash-chained audit log,
   FERPA + GDPR alignment.
7. mypy --strict + 90% / 80% coverage, property tests, snapshot tests,
   cassette replay, OpenTelemetry observability + SLOs as code.
8. Multi-package Python monorepo (uv workspace) + sibling TypeScript SDK
   (pnpm); enforced dependency direction via `import-linter`. 12-phase
   build sequence with MVP cut at Phase 11.

## Consequences

- Adding new languages, target systems, pipelines, or SLA tiers is YAML
  work — no Python required for the common case.
- Multi-provider routing decouples cost / accuracy / region / compliance
  from business logic.
- Per-tenant overrides at every layer support enterprise customization
  without forking.
- The MVP delivery cost is higher than a Polish-only hardcoded approach,
  but the architecture is reusable for any future expansion without
  rewrite.

## References

- `docs/plans/2026-04-25-ocr-to-report-design.md` — full plan.
- Source PDF for original requirements: `Workflow cho Quốc.pdf` (provided
  by user; not committed).

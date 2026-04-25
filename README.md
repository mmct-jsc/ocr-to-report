# OCR-to-Report

Schema-driven multi-language transcript-to-report SaaS.

| Status | Phase 0 (Bootstrap) — repo skeleton, CI green, `make dev` brings up empty stack |
|---|---|
| Plan | [`docs/plans/2026-04-25-ocr-to-report-design.md`](docs/plans/2026-04-25-ocr-to-report-design.md) |
| License | MIT |

---

## What this is

An open, plugin-style platform that converts school transcripts (initially
Polish ŚWIADECTWO SZKOLNE; ultimately any language and education system) into
target-system reports (initially a US High School Grade 9 Excel template;
ultimately any tabular/document target).

External systems integrate via **REST**, **Python SDK**, **TypeScript SDK**,
**CLI**, or **MCP server** — all backed by the same `core`. Multiple AI/OCR
providers (Anthropic, OpenAI, Google, Tesseract) plug in behind a single
adapter interface. Every aspect of the workflow — pipelines, SLA tier,
retention, encryption, region — is configurable per tenant.

## Quick start

Prerequisites: `uv ≥ 0.10`, `docker ≥ 24`, `docker compose v2`, `make`.

```bash
# 1. Install workspace deps + pre-commit hooks
make install

# 2. Bring up the dev stack (postgres + redis + minio + api)
make dev

# 3. Verify it's alive
curl http://localhost:8000/v1/health
# → {"status":"ok"}

# 4. Run the test suite
make test
```

Common targets — `make help` for the full list.

## Repository layout

```
packages/{core,adapters,api,worker,cli,sdk_py,mcp}/  Python workspace members
sdk-ts/                                              TypeScript SDK (pnpm)
profiles/<lang>.<doc>.<version>/                     Source profile bundles
targets/<system>.<version>/                          Target system bundles
pipelines/                                           Workflow pipeline YAML
sla-tiers/                                           SLA tier presets YAML
migrations/                                          Alembic migrations
docker/                                              Multi-stage Dockerfiles
deploy/                                              Compose + Helm charts
docs/                                                Design plans, runbooks, ADRs
tests/                                               Cross-package fixtures + suites
```

Dependency direction (enforced by `import-linter` in CI):

```
core ← adapters ← {api, worker, cli, mcp}
                       ↖ sdk_py (HTTP only — never imports server-side code)
```

## Documentation

- [Architecture](ARCHITECTURE.md) — runtime topology, module boundaries
- [Security](SECURITY.md) — threat model, reporting policy
- [Contributing](CONTRIBUTING.md) — dev workflow, test conventions, PR rules
- [Design plan](docs/plans/2026-04-25-ocr-to-report-design.md) — locked
  decisions and phased build sequence

## License

MIT — see [`LICENSE`](LICENSE).

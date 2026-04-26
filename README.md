# OCR-to-Report

Schema-driven multi-language transcript-to-report SaaS.

| Status | **v0.1.0** — all 12 phases shipped + production web console |
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
**CLI**, **MCP server**, or the **Web Operations Console** — all backed by the
same `core`. Multiple AI/OCR providers (Anthropic, OpenAI, Google, Tesseract)
plug in behind a single adapter interface. Every aspect of the workflow —
pipelines, SLA tier, retention, encryption, region — is configurable per tenant.

![Dashboard](docs/ui/dashboard-light.png)

## Quick start

Prerequisites: `uv ≥ 0.10`, `docker ≥ 24`, `docker compose v2`, `make`.
(Node + npm are only needed if you want to develop the web console outside
docker — the production image is built inside the compose `web` stage.)

```bash
# 1. Install Python workspace deps + pre-commit hooks
make install

# 2. Drop your Anthropic key + a fresh KEK into .env
cat > .env <<EOF
OCR2R_KEK_B64=$(python -c 'import base64,secrets;print(base64.b64encode(secrets.token_bytes(32)).decode())')
ANTHROPIC_API_KEY=sk-ant-...
EOF

# 3. Bring up the full stack (postgres + redis + minio + api + worker + web)
docker compose up -d

# 4. Bootstrap a tenant + API key (printed once — save it)
OCR2R_KEK_B64="$(grep '^OCR2R_KEK_B64' .env | cut -d= -f2)" \
OCR2R_DATABASE_URL="postgresql+asyncpg://ocr2r:ocr2r@localhost:5432/ocr2r" \
uv run ocr-to-report bootstrap --name Acme --slug acme

# 5. Verify the API
curl -H "Authorization: Bearer <key from step 4>" \
     http://localhost:8000/v1/usage

# 6. Open the web console
#    → http://localhost:5173  (nginx serves the SPA + proxies /api → api:8000)
#    paste the key from step 4 on the login screen

# 7. Run the test suite
make test
```

Common targets — `make help` for the full list.

### Service map

| Container | Port | Role |
|---|---:|---|
| `web` | 5173 | nginx serving the static SPA + `/api/*` proxy to the API |
| `api` | 8000 | FastAPI v1 surface |
| `worker` | — | Async task consumer (batch + retention) |
| `postgres` | 5432 | Tenants, jobs, transcripts (encrypted), audit chain |
| `redis` | 6379 | Reserved for the production queue backend |
| `minio` | 9000 / 9001 | S3-compatible blob store + admin console |

## Web console

Single-page Vite + React + Tailwind app (in `web/`) driven by the published
TypeScript SDK. Pages cover every v1 surface: dashboard, process (drag-and-
drop upload), jobs list, job detail with download/approve/reject, webhooks,
GDPR DSR (access/portability/erasure), templates, settings. Light + dark
themes. Live API health pulse in the sidebar.

Keys with the `admin:*` scope unlock an extra **Admin** section (System,
Tenants) plus a topbar **TenantSwitcher** dropdown that lets an admin view
any tenant's dashboard, jobs, webhooks, compliance, and settings — switching
the API context via the `X-Acting-Tenant-Id` header. Every impersonated
request appends a `tenant.impersonated_access` audit row on the *target*
tenant, so the data owner can see who looked and when.

In production, the SPA is built inside `docker/web.Dockerfile` and served by
nginx (`docker/web.nginx.conf`); the same nginx proxies `/api/*` to the API
container so the browser stays same-origin (no CORS, no preflights). For
local development on the SPA itself, `cd web && npm install && npm run dev`
gives you HMR — Vite's own proxy still routes `/api` to `localhost:8000`.

| | |
|---|---|
| ![Upload](docs/ui/upload-with-file.png) | ![Job detail](docs/ui/job-after-upload.png) |
| ![Compliance](docs/ui/compliance.png) | ![Dark](docs/ui/dashboard-dark.png) |

## Repository layout

```
packages/{core,adapters,api,worker,cli,sdk_py,mcp}/  Python workspace members
sdk-ts/                                              TypeScript SDK (npm)
web/                                                 Web Operations Console (Vite + React)
profiles/<lang>.<doc>.<version>/                     Source profile bundles
targets/<system>.<version>/                          Target system bundles
pipelines/                                           Workflow pipeline YAML
sla-tiers/                                           SLA tier presets YAML
observability/                                       Prometheus alerts + Grafana dashboard
migrations/                                          Alembic migrations
docker/                                              Multi-stage Dockerfiles
deploy/                                              Compose + Helm charts
docs/                                                Design plans, runbooks, ADRs, UI screens
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
- [Budget](docs/BUDGET.md) — production cost model, real benchmark, tier pricing
- [Design plan](docs/plans/2026-04-25-ocr-to-report-design.md) — locked
  decisions and phased build sequence
- [CHANGELOG](CHANGELOG.md) — full v0.1.0 entry covering every phase

## License

MIT — see [`LICENSE`](LICENSE).

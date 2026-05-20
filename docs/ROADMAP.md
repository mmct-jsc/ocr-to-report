# OCR-to-Report — Product Roadmap

| Owner | QuocTran |
|---|---|
| Last updated | 2026-04-29 |
| Current version | `v0.1.0+cors` |
| Next milestone | `v0.2.0` — Per-tenant customization |
| Plan for next milestone | [`docs/plans/2026-04-29-v0.2.0-tenant-overrides.md`](plans/2026-04-29-v0.2.0-tenant-overrides.md) |

This document maps the full product trajectory from the shipped MVP through
General Availability. Each row in [§3](#3-version-trajectory) names a
release, its theme, the user-visible features it ships, the schema/code
surfaces it touches, and the acceptance bar that gates the tag.

For *why* the system is shaped the way it is, read
[`docs/plans/2026-04-25-ocr-to-report-design.md`](plans/2026-04-25-ocr-to-report-design.md)
first — this roadmap presupposes those Decisions.

---

## 1. Product Thesis

OCR-to-Report is a **multi-tenant SaaS** that converts education-record
documents into target-system reports. To serve real customers it must be
**fully manageable** by the platform owner *and* **fully customizable**
by each tenant — workflow, template, SLA, subscription, model, key, and
language all individually swappable without code changes.

Every roadmap item below maps to one of those axes.

```
                 ┌──────────────────── manageable ─────────────────┐
                 │  admin: tenants, keys, audit, system, billing   │
                 │  ops:   runbooks, alerts, SLO dashboard         │
                 └─────────────────────────────────────────────────┘
                                       │
            ┌──────────────────── customizable ────────────────────┐
            │  workflow   ←  per-tenant pipeline overrides         │
            │  template   ←  per-tenant xlsx/docx/pdf templates    │
            │  SLA        ←  per-field overrides on top of presets │
            │  provider   ←  tenant picks Anthropic / OpenAI / …   │
            │  model      ←  tenant picks Haiku / Sonnet / GPT-4o  │
            │  key (BYOK) ←  tenant supplies its own provider key  │
            │  language   ←  source profile + UI locale + outputs  │
            │  billing    ←  tenant picks plan, quotas, payment    │
            └──────────────────────────────────────────────────────┘
```

A roadmap entry is **done** when (a) the schema is migrated, (b) the API
surface is implemented and documented, (c) the SDKs expose it, (d) the
web console exposes it, (e) tests cover the new paths, and (f) the
CHANGELOG entry is written. Anything short of all six is "in progress."

---

## 2. Where We Are Today

### Shipped — `v0.1.0` (2026-04-25)

Polish ŚWIADECTWO SZKOLNE → US-HS Grade 9 Excel, end to end, on a
schema-driven foundation. 12 phases, ~500 tests, multi-provider vision
router (Anthropic full; OpenAI/Google/Tesseract scaffolded), Postgres
RLS + envelope encryption, hash-chained audit, GDPR DSRs, OTel
metrics/traces/alerts, Docker Compose stack.

### Shipped — `v0.1.0+ui` (2026-04-26)

Web Operations Console: dashboard, process, jobs, webhooks, compliance,
templates, settings — all driven by the published TS SDK. Light + dark
themes. nginx serves SPA + proxies `/api`.

### Shipped — `v0.1.0+admin` (2026-04-26)

`/v1/admin/*` endpoints (system, tenants CRUD, API keys, audit log) gated
on `admin:*`. Admin section in the web console. **Tenant impersonation**
via `X-Acting-Tenant-Id` with audit on the target tenant — admins can
view *any* tenant's dashboard/jobs/webhooks/compliance/settings without
re-authenticating.

### Shipped — `v0.1.0+cors` (2026-04-29)

CORS middleware (opt-in via `OCR2R_CORS_ALLOWED_ORIGINS` /
`OCR2R_CORS_ALLOWED_ORIGIN_REGEX`) so browser-driven SDK consumers on a
different origin can succeed their `OPTIONS` preflight. Compose seeds
`https://.*\.trycloudflare\.com` regex for tunnel-sharing workflows.

Also shipped this round (not version-tagged): public `/demo` route in
the web console (unauthenticated feature tour with the full
screenshot gallery), tag-triggered release pipeline at
`.github/workflows/release.yml` (multi-arch GHCR push, SBOM, cosign
keyless signing, GitHub Release auto-extracted from CHANGELOG), and
this version of the roadmap. 58 Python + 15 TS tests passing.

---

## 3. Version Trajectory

The following minor versions deliver the customization promised by the
design plan plus the SaaS-foundation features needed to charge for the
product. Each version is independently releasable.

### `v0.2.0` — Per-tenant customization (the foundation)

> Activates the `tenant_overrides` table that has been a TODO in
> `models.py` since Phase 5. Everything from v0.3 onwards depends on
> this resolver.

**User stories**
- *As a tenant admin, I can pick a different pipeline (e.g.,
  `with_manual_review_v1` instead of `default_v1`) from the Settings page.*
- *As a tenant admin, I can raise my confidence threshold from 0.85 to
  0.95 without paying for the Premium tier.*
- *As a tenant admin, I can upload a custom xlsx template for a target
  (e.g., my own Grade-9 layout) and have new jobs render against it.*
- *As a tenant admin, I can add subject-name aliases to the Polish
  vocabulary that haven't been merged upstream.*

**Surfaces**
- DB: activate `tenant_overrides` (path-based JSONB patches), index by
  `(tenant_id, scope)`.
- Core: `OverrideResolver(deep_merge)` consumed by `ProfileRegistry`,
  `TargetRegistry`, `PipelineRegistry`, `TenantSlaConfig`.
- API: `GET/PUT /v1/tenant/config` + `GET/POST/DELETE /v1/pipelines`
  + `POST /v1/templates/upload`.
- SDK: `client.tenantConfig.get/update`, `client.pipelines.*`,
  `client.templates.upload`.
- Web: Settings page gains tabs *Pipeline*, *SLA overrides*, *Templates*,
  *Vocabulary patches*. Each tab edits a JSON patch with live diff
  preview against the resolved baseline.

**Acceptance**
- A non-admin tenant can flip pipeline + SLA threshold + template via
  the UI; the next job uses the new resolved config; an admin viewing
  through impersonation sees identical behavior.

---

### `v0.3.0` — Provider choice + BYOK

> Tenants pick the provider+model that fits their cost, latency, or
> compliance constraints — and supply their own API key when they
> already have a vendor relationship. Cost reporting splits between
> "platform-billed" and "tenant-billed" calls.

**User stories**
- *As an EU tenant, I require all vision calls to go to Vertex AI in
  europe-west1 — no Anthropic.*
- *As a tenant with an Anthropic Enterprise contract, I supply my own
  `ANTHROPIC_API_KEY` and the platform routes my jobs through it.*
- *As a tenant on Standard, I want Sonnet-only (no Haiku-first) because
  my documents are noisy.*

**Surfaces**
- DB: new `tenant_provider_credentials` table — `(tenant_id, provider,
  encrypted_api_key, model_overrides_json, region, active)`. Encrypted
  with the per-tenant DEK; rotation tracked in audit.
- Core: `ProviderRouter` accepts a `TenantProviderConfig` ahead of the
  global router; the SLA tier becomes the *default*, not a hard rule.
- Adapters: each `*VisionAdapter` accepts an injected key+endpoint at
  call time (so the same adapter handles both platform and tenant
  credentials).
- API: `GET/PUT /v1/tenant/providers` (list + upsert), audit on
  add/rotate/revoke.
- Web: Settings → *Providers* tab. Lists configured providers with
  test-connection button. Adding a new key shows a key-validation
  call before persisting.
- Cost: `usage_records.billing_path` ∈ {`platform`, `byok`} so
  invoicing in v0.4 ignores byok rows.

**Acceptance**
- Two tenants can run the same transcript on the same SLA tier through
  *different* providers + models, billed correctly, with audit entries
  showing key rotation history.

---

### `v0.4.0` — Subscription, plans, quotas, metering

> Turns the prototype into a product that bills. Plans gate features
> from earlier versions (e.g., per-tenant template upload may be
> Premium+). Hard quota enforcement protects the platform from runaway
> tenants.

**User stories**
- *As the platform owner, I price per transcript with monthly tiers, a
  free trial, and overage rates.*
- *As a tenant, I see my current usage vs. quota on the dashboard, get
  warned at 80% and 100%, and can upgrade plan in-app.*
- *As the platform owner, I can issue refunds, credits, and per-tenant
  pricing overrides without a deploy.*

**Surfaces**
- DB: `plans` (name, monthly_price, transcript_quota, sla_max_tier,
  features_json), `subscriptions` (tenant_id, plan_id, billing_period,
  status, started_at, canceled_at), `invoices`, `payment_methods`.
- Adapters: `StripeBilling` (Checkout + Customer Portal + webhooks) +
  `ManualBilling` for self-hosted.
- Core: `QuotaGate` middleware → 429 with `Retry-After` when over;
  `MeterPublisher` posts `usage.transcript.completed` events to
  Stripe's metered billing.
- API: `GET /v1/billing/subscription`, `POST /v1/billing/checkout`,
  `POST /v1/billing/portal`, webhook receiver
  `POST /v1/billing/stripe/webhook`.
- Web: new **Billing** page (plan, current spend, quota gauge,
  invoices, payment method, change-plan flow). Admin gets a *Plans*
  manager.

**Acceptance**
- A new tenant can sign up, pick a plan, hit Stripe checkout, return
  with their plan active, run jobs until the quota fires a 429, then
  upgrade in-app and continue.

---

### `v0.5.0` — Localization (i18n)

> The core has been language-neutral since Phase 2 (it's literally the
> point of the canonical IR). v0.5 makes the UI and outbound
> communication match — error messages, emails, and the web console
> all speak the user's language.

**User stories**
- *As a Polish school admin, I view the web console in Polish, get
  Polish error messages from the API, and receive Polish-translated
  manual-review emails.*
- *As a Vietnamese tenant, I switch to `vi-VN` and the entire console,
  including dates and currency, localizes.*

**Surfaces**
- Web: `react-i18next` with locale resource files
  (`web/locales/{en,pl,vi,es,de,fr}.json`); locale picker in topbar;
  preference persisted on `User.locale`.
- API: every error in `errors/domain.py` carries an `i18n_key`; the
  problem+json renderer accepts `Accept-Language` and substitutes the
  translated `title` + `detail`.
- Core: locale-aware date / number / currency formatters in
  `core.format`.
- DB: add `locale` to `users` and `tenants` (default `en-US`).
- Output renderers: xlsx headers translate based on tenant locale
  (the canonical IR stays English internally — only the rendered
  surface localizes).
- Email: webhook + manual-review notification templates pulled from
  `templates/email/<locale>.j2`.

**Acceptance**
- Switching the locale flips every visible string + every API error
  body without reload artifacts; six locales ship; missing-key
  fallback to English with a console warning.

---

### `v0.6.0` — Source + target catalog expansion

> Adding a profile or target is YAML-only by design (Phase 2). v0.6
> exercises that promise by shipping four new bundles, validating
> the architecture against more languages and education systems.

**User stories**
- *As a Vietnamese parent, I upload a HỌC BẠ (`vi.thpt.hocba.v1`) and
  get the same US-HS output.*
- *As a UK admissions officer, I render the canonical IR into the UCAS
  Predicted Grades form (`uk-ucas.v1`).*
- *As a US community college, I receive transfer credit data in
  `us-college.v1`.*

**Bundles**
- Profiles: `vi.thpt.hocba.v1`, `es.eso.boletin.v1`, `de.abitur.v1`,
  `fr.bac.v1`.
- Targets: `us-college.v1`, `uk-ucas.v1`, `ib-dp.v1`.

**Validation**
- Snapshot tests per profile×target combination on anonymized
  fixtures; cassettes pinned to a specific provider/model for cost
  determinism.
- Profile authors guide upgraded
  (`CONTRIBUTING_PROFILE.md` + a video walkthrough in `docs/howto/`).

---

### `v0.7.0` — Provider expansion (full implementations)

> Replaces the `NotImplementedError` stubs from Phase 3 with full
> adapters. v0.3 made provider choice tenant-visible; v0.7 makes it
> meaningful by giving them more than one real option.

- `OpenAIVisionAdapter` (gpt-4o + gpt-4o-mini, structured outputs).
- `GoogleVisionAdapter` (Gemini 2.x via Vertex AI; eu/us regions).
- `TesseractAdapter` (on-prem fallback for air-gapped tenants).
- Per-provider cassette suite + nightly live verification.
- Cost tables in `docs/BUDGET.md` regenerated.

**Acceptance**
- Each adapter passes a shared protocol-conformance test suite; tenant
  routing through a non-Anthropic provider is verified in CI.

---

### `v0.8.0` — Compliance + enterprise hardening

> The plan called these out as "deferred to v1.1+." A serious B2B sale
> needs at least the first three.

- **KMS / HSM** integration (AWS KMS, GCP KMS, Vault) replacing the
  env-based KEK; rotation tested.
- **WORM audit** (S3 Object Lock) for Premium tier; auditor-export
  endpoint.
- **SIEM export** (Splunk HEC, Datadog, Elastic) for Enterprise tier.
- **OIDC / SAML SSO** for the web console (Auth0, Okta, Keycloak).
- **SOC 2 Type 1** scoped + readiness assessment; auditor pack in
  `docs/compliance/`.
- **Egress allowlist** as a first-class deny-by-default policy
  (Phase 5 shipped a permissive default).

---

### `v0.9.0` — Output renderers + custom mapping UI

> XLSX-only is fine for the MVP customer (high schools); colleges and
> immigration cases want PDF and DOCX. Custom mapping UI moves the
> template-overrides from raw JSON to a visual editor.

- `DocxRenderer` (python-docx) — translates the canonical IR through
  the same template-key system.
- `PdfRenderer` (WeasyPrint) — HTML/CSS templates produce filled PDFs
  with embedded fonts.
- **Mapping editor** in the web console: drag-and-drop canonical IR
  fields to template anchors (xlsx cells / docx merge fields / pdf
  form fields). Saves as a `tenant_overrides` patch from v0.2.

---

### `v1.0.0` — General Availability

> Cuts the `0.x` rollercoaster. v1.0 is when we charge external
> customers and promise stability.

- **Helm chart** + tested deployments on EKS, GKE, AKS, k3s.
- **Multi-region** active-active with row-level region pinning (the
  data layer was built for this in Phase 5; v1.0 wires it up).
- **Custom step plugin loader** — entry-point discovery for tenants
  that ship Python steps (sandboxed via WASI runtime; protocol
  unchanged from Phase 4).
- **ML-based profile auto-fingerprinting** — replaces the Phase 2
  regex detector with a small classifier trained on shipped profile
  samples.
- **Performance**: load test at 100k transcripts/day sustained.
- **Operational**: `docs/runbooks/` populated (incident response,
  audit-chain repair, key rotation, restore from backup, scale-up).
- **SOC 2 Type 1** attestation completed; HIPAA + ISO 27001 readiness
  assessments.

**Acceptance**
- A new customer can sign up, configure their tenant, supply BYOK or
  use platform billing, run jobs through their chosen pipeline +
  template + SLA + locale, see audit + usage + cost, hit no
  documentation gaps, and pass an external pen test.

---

## 4. Feature → Version Map (your vision, decoded)

| You asked for… | Lands in | Notes |
|---|---|---|
| Fully **manageable** by platform owner | `0.1.0+admin` ✓ + ongoing | Admin section + impersonation shipped; v0.4 adds plan/billing admin; v0.8 adds SOC 2 surfaces; v1.0 ships runbooks. |
| Per-tenant **workflow** customization | **`v0.2.0`** | Custom pipeline upload + selection + override. |
| Per-tenant **template** customization | **`v0.2.0`** + visual editor in `v0.9.0` | Raw upload first; UI editor when output renderers expand. |
| Per-tenant **SLA format** | **`v0.2.0`** | Per-field overrides on top of presets. |
| Per-tenant **subscription** | **`v0.4.0`** | Plans, quotas, Stripe integration. |
| Pick **model** from provider | **`v0.3.0`** | Per-tenant model override; provider choice. |
| Use **own API key** (BYOK) | **`v0.3.0`** | Encrypted per-tenant credentials, audited rotations. |
| **Localization** | **`v0.5.0`** | Web + API + email; six initial locales. |
| Each aspect has **its own workflow + template + SLA** | Foundation in `v0.2.0`; consumed by all later versions | The override resolver is the lever — every customizable axis lands as a `tenant_overrides` patch. |

---

## 5. Cross-Cutting Concerns (every version)

These run alongside, not as a release:

- **Test coverage** — every new endpoint adds property + integration +
  contract (`schemathesis`) tests. Coverage floor 80% overall, 90% on
  `core/`.
- **Migration safety** — Alembic migrations are forward-only; each one
  is dry-run on a staging clone before tagging.
- **Security review** — every PR touching auth / encryption / audit /
  egress gets an explicit `@security` label and a second reviewer.
- **Observability** — every new feature ships with at least one
  Prometheus metric, one log field, and one alert rule if applicable.
- **Documentation** — README, ARCHITECTURE, CHANGELOG, and this
  ROADMAP are updated *in the same PR* as the code. Stale docs are
  treated as bugs.

---

## 6. Out of Scope (not on the roadmap)

These are intentionally **not** planned. If a customer asks for them,
the answer is "no" or "in a fork":

- **Live human transcription** — we OCR finished documents, not
  in-progress dictation.
- **Generic document AI** — the canonical IR is education-record-shaped.
  Invoices, contracts, prescriptions, etc., are out of scope.
- **Customer-managed Postgres extensions** — the schema is ours; we
  manage migrations.
- **Self-serve white-label / re-branding** beyond the per-tenant logo
  + accent color planned for v0.5.

---

## 7. How This Doc Stays Honest

- A version is **not released** until every row in
  [§3](#3-version-trajectory) for it is checked.
- A new request that doesn't fit an existing version opens a
  new minor version slot; we do not silently expand a tagged scope.
- A version slips by **shrinking scope, not the bar**. If `v0.4`
  cannot ship Stripe by date, drop Stripe to `v0.4.1`; do not ship
  half-tested billing.
- The `last updated` date at the top reflects the most recent material
  edit. Renumbering without changing meaning does not update it.

For decisions that materially change the trajectory, write an ADR in
[`docs/adr/`](adr/) and link it from the affected row above.

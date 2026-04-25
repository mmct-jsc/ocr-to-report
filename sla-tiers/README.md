# SLA tier presets

Four tiers shipped in MVP (introduced in Phase 8):

- `economy.yaml` — batch-only, slowest, cheapest. Confidence ≥ 0.80.
- `standard.yaml` — default, sync allowed, Haiku primary. Confidence ≥ 0.85.
- `premium.yaml` — Sonnet primary, region-pinned, encrypted DEK + HSM-ready.
- `enterprise.yaml` — fully custom, SLA-credited, dedicated capacity.

Each tier is a YAML preset that fills the `TenantSlaConfig` Pydantic model.
Tenants pick a tier and may override individual fields without leaving the
tier (per-field overrides are stored under `tenant_overrides`).

Phase 0 is scaffold only.

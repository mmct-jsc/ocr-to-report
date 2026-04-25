-- Postgres Row Level Security (RLS) policies for OCR-to-Report.
--
-- Apply once after Alembic creates the tables (Phase 6 wires Alembic
-- proper). Production deploys MUST run this; SQLite-based unit tests
-- skip RLS since the dialect doesn't support it.
--
-- The application layer also filters by tenant_id in every query (see
-- packages/adapters/src/ocr_to_report/adapters/db/repositories/) — RLS
-- is the third defense-in-depth layer (after app-level filter + ORM
-- session SET LOCAL).
--
-- Pattern: every tenant-scoped table has a policy that compares its
-- ``tenant_id`` column to ``current_setting('app.tenant_id', true)``,
-- which the app sets via ``SET LOCAL app.tenant_id = '<uuid>'`` at the
-- start of every request (see ``adapters/db/session.py``).
--
-- See docs/plans/2026-04-25-ocr-to-report-design.md §6.B for the full
-- threat model and rationale.

-- ─── Enable RLS on every tenant-scoped table ─────────────────
ALTER TABLE api_keys              ENABLE ROW LEVEL SECURITY;
ALTER TABLE webhooks              ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE transcripts           ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log             ENABLE ROW LEVEL SECURITY;
ALTER TABLE usage_records         ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys      ENABLE ROW LEVEL SECURITY;
-- result_cache may be cross-tenant by design; left without RLS for now.

-- ─── Force RLS even for table owners ─────────────────────────
-- Without FORCE, the user that owns the table bypasses RLS. The app
-- connects as a non-superuser role; FORCE makes the policy apply even
-- when running migrations as the owner.
ALTER TABLE api_keys              FORCE ROW LEVEL SECURITY;
ALTER TABLE webhooks              FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs                  FORCE ROW LEVEL SECURITY;
ALTER TABLE transcripts           FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_log             FORCE ROW LEVEL SECURITY;
ALTER TABLE usage_records         FORCE ROW LEVEL SECURITY;
ALTER TABLE idempotency_keys      FORCE ROW LEVEL SECURITY;

-- ─── Per-table policies ──────────────────────────────────────
-- For each table, two policies:
--   (a) When app.tenant_id is set → restrict to that tenant.
--   (b) When app.tenant_id is NULL/missing → allow all (admin/migrate).
--
-- The app sets app.tenant_id via SET LOCAL inside every request
-- transaction (`tenant_scoped_session`); migrations and CLI tools run
-- without setting it and use the bypass policy.

CREATE POLICY tenant_isolation_api_keys ON api_keys
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_webhooks ON webhooks
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_jobs ON jobs
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_transcripts ON transcripts
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_audit_log ON audit_log
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_usage_records ON usage_records
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

CREATE POLICY tenant_isolation_idempotency_keys ON idempotency_keys
    USING (
        tenant_id::text = current_setting('app.tenant_id', true)
        OR current_setting('app.tenant_id', true) IS NULL
        OR current_setting('app.tenant_id', true) = ''
    );

-- ─── Indexes (deferred to Alembic migrations) ─────────────────
-- The SQLAlchemy models declare every required Index; Alembic emits
-- them on first migration apply. Listed here as documentation only:
--
--   ix_api_keys_tenant_id, ix_api_keys_prefix
--   ix_webhooks_tenant_id
--   ix_jobs_tenant_id, ix_jobs_status,
--     uq_jobs_tenant_idempotency (tenant_id, idempotency_key)
--   ix_transcripts_tenant_id,
--     ix_transcripts_input_sha256 (tenant_id, input_sha256)
--   ix_audit_log_tenant_ts (tenant_id, ts),
--     ix_audit_log_resource (resource_type, resource_id)
--   uq_usage_tenant_period (tenant_id, period_start, period_end)
--   uq_idempotency_tenant_key (tenant_id, key)

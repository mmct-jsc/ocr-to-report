# Runbook — Empty Database Recovery

> **Symptom:** Every authenticated endpoint returns `500 Internal Server Error`. The web Operations Console says **"API not reachable"** or **"The probe returned 500"**. `/v1/health` still returns `200`. API logs contain `UndefinedTableError: relation "api_keys" does not exist`.

This happens when the Postgres data volume was destroyed but the API container is running. Compose brings everything back up cleanly, but no automatic schema-create runs on boot (until v0.2.0 wires alembic in). The DB is reachable and authenticates the `ocr2r` user, but it has zero tables — so every `SELECT FROM api_keys` blows up at the SQL layer.

## When this happens

* `docker compose down -v` (the `-v` removes named volumes).
* Manually running `docker volume rm ocr2r_postgres_data`.
* Docker Desktop → Settings → "Reset to factory defaults" or "Clean / Purge data".
* First-time stack bring-up on a clean checkout, before bootstrap has been run.

## 1-line diagnosis

```bash
docker compose exec -T postgres psql -U ocr2r -d ocr2r -c "\dt"
```

* `Did not find any relations` → empty schema (this runbook applies).
* List of tables (`tenants`, `api_keys`, `jobs`, …) → schema is fine; the 500 is something else, **stop reading**.

Or, after `v0.1.0+resilience`, ask the API directly:

```bash
curl -sS http://127.0.0.1:8000/v1/ready | jq .
```

* `"database": "schema_missing"` → empty schema (this runbook applies).
* `"database": "unreachable"` → connection / credentials issue, not this runbook.
* `"database": "ready"` → schema is fine.

## Fix — three options, easiest first

### Option 1 — Auto-migrate on next boot (dev-only)

Add to `.env`:

```bash
OCR2R_AUTO_MIGRATE_ON_BOOT=true
```

Restart the API container:

```bash
docker compose restart api
```

The lifespan will call `Base.metadata.create_all` and the schema will be present. Authenticated endpoints work again. No tenant or key is seeded — you still need Option 2 or 3 to get a usable token.

**Do NOT leave this on in production.** Schema changes in prod must go through alembic (arriving in v0.2.0). Toggle it off once you're past the recovery.

### Option 2 — Bootstrap CLI from the host

If the API container is healthy but you need a tenant + key:

```bash
# from the repo root, with .venv activated
export OCR2R_KEK_B64="$(grep '^OCR2R_KEK_B64=' .env | cut -d= -f2-)"
export OCR2R_DATABASE_URL="postgresql+asyncpg://ocr2r:ocr2r@127.0.0.1:5432/ocr2r"

# Mint an admin tenant + key
python -c "
import asyncio, time
from ocr_to_report.cli.bootstrap import _run
asyncio.run(_run(
    name='Acme',
    slug=f'acme-{int(time.time())}',
    database_url=None,
    sla_tier='premium',
    admin=True,
))
"
```

The CLI prints `tenant_id` and `api_key`. Save the key — it is Argon2id-hashed in the DB and cannot be recovered.

**Common gotcha:** `cut -d= -f2` (without the trailing `-`) eats the trailing `=` of the base64-encoded KEK. Always use `cut -d= -f2-` so the full value comes through. If you see `CryptoError: environment variable 'OCR2R_KEK_B64' is not valid base64`, this is the cause.

### Option 3 — Bootstrap CLI from inside a container

If your host doesn't have the Python workspace installed, run from inside the worker container (which has the same code):

```bash
docker compose exec worker python -c "
import asyncio, time
from ocr_to_report.cli.bootstrap import _run
asyncio.run(_run(
    name='Acme',
    slug=f'acme-{int(time.time())}',
    database_url=None,
    sla_tier='premium',
    admin=True,
))
"
```

The worker container inherits `OCR2R_KEK_B64` and `OCR2R_DATABASE_URL` from compose env, so no manual exports needed.

## Verify the recovery

```bash
# Schema is back
docker compose exec -T postgres psql -U ocr2r -d ocr2r -c "\dt" | head -5

# Authenticated endpoint works
curl -sS -o /dev/null -w "HTTP %{http_code}\n" \
  -H "Authorization: Bearer sk_test_…YOUR_KEY…" \
  http://127.0.0.1:8000/v1/usage
# expected: HTTP 200

# Readiness reports green
curl -sS http://127.0.0.1:8000/v1/ready | jq '.status, .checks.database'
# expected: "ok"  "ready"
```

## Why this happens — the technical explanation

Today the schema is created by `Base.metadata.create_all` in only two paths:

1. `ocr-to-report bootstrap` — the seed CLI.
2. The test fixtures — `await conn.run_sync(Base.metadata.create_all)`.

Neither runs at API container startup. The lifespan in `packages/api/src/ocr_to_report/api/app.py` builds long-lived adapters (encryptor, blob, vision router, etc.) but does **not** touch the schema. So a fresh empty Postgres volume + a healthy API container = silent schema absence, surfaced only when the first `SELECT FROM api_keys` runs in `authenticate()`.

`v0.2.0` (per `docs/plans/2026-04-29-v0.2.0-tenant-overrides.md`, Task 1) introduces alembic baselines + a real migration path. After that ships, the auto-migrate hook will call `alembic upgrade head` instead of `create_all`, and the recovery becomes a single `make migrate`.

## Prevention

* **Dev / CI:** set `OCR2R_AUTO_MIGRATE_ON_BOOT=true` in `.env` so the recovery happens automatically next time a fresh volume comes up. (Recommended for any local dev setup.)
* **Staging / production:** keep the flag off and run schema changes through your migration pipeline. Add a deploy-step check that calls `/v1/ready` and fails the rollout if `checks.database != "ready"`.
* **Backups:** named volumes vanish silently. For long-lived state, mount the postgres data directory at a path you back up explicitly, or use a managed Postgres service.

## Related

* [`docs/plans/2026-04-29-v0.2.0-tenant-overrides.md`](../plans/2026-04-29-v0.2.0-tenant-overrides.md) — Task 1 introduces alembic.
* [`packages/cli/src/ocr_to_report/cli/bootstrap.py`](../../packages/cli/src/ocr_to_report/cli/bootstrap.py) — the seed CLI.
* [`packages/api/src/ocr_to_report/api/app.py`](../../packages/api/src/ocr_to_report/api/app.py) — the lifespan + auto-migrate hook.

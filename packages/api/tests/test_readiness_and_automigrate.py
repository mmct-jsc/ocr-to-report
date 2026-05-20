"""``/v1/ready`` deep checks + opt-in auto-migrate on boot.

These two changes ship together because they're the defensive pair for
the same failure mode: a fresh / empty database silently 500s every
authenticated endpoint because no one ran ``ocr-to-report bootstrap``.

* ``/v1/ready`` learns to probe the database. When the schema is
  missing it returns 503 with ``checks.database == "schema_missing"``
  instead of always-200, so kubectl readinessProbe + the web SPA both
  surface a useful error.

* ``OCR2R_AUTO_MIGRATE_ON_BOOT=true`` (env / settings, default off)
  runs ``Base.metadata.create_all`` during the FastAPI lifespan so a
  fresh dev volume self-heals. Off by default — production deploys
  should run migrations through alembic out-of-band.
"""

from __future__ import annotations

import base64
import secrets
from pathlib import Path

from fastapi.testclient import TestClient

from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.api.app import create_app
from ocr_to_report.api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


def _fresh_settings(tmp_path: Path, *, auto_migrate: bool = False) -> Settings:
    return Settings(
        env="development",
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        blob_backend="local",
        blob_local_root=tmp_path / "blob",
        kek_b64=base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
        profiles_root=REPO_ROOT / "profiles",
        targets_root=REPO_ROOT / "targets",
        auto_migrate_on_boot=auto_migrate,
    )


# ─── Part 1: /v1/ready deep checks ─────────────────────────────


def test_ready_reports_schema_missing_when_db_empty(tmp_path: Path) -> None:
    """Fresh SQLite file — no tables — must surface schema_missing + 503.

    Without this signal, every authenticated endpoint 500s opaquely;
    the operator has to dig through logs to find ``UndefinedTableError``.
    """
    app = create_app(settings=_fresh_settings(tmp_path))
    with TestClient(app) as c:
        r = c.get("/v1/ready")
    assert r.status_code == 503, r.text
    body = r.json()
    assert body["status"] == "degraded"
    assert body["checks"]["database"] == "schema_missing"


def test_ready_returns_200_when_schema_present(tmp_path: Path) -> None:
    """Schema exists → all checks pass → 200.

    Uses the auto_migrate flag as the most ergonomic way to populate
    the schema; the second auto-migrate test covers that path
    independently, so re-using it here is intentional.
    """
    settings = _fresh_settings(tmp_path, auto_migrate=True)
    app = create_app(settings=settings)
    with TestClient(app) as c:
        r = c.get("/v1/ready")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert body["checks"]["database"] == "ready"


# ─── Part 2: OCR2R_AUTO_MIGRATE_ON_BOOT=true ───────────────────


def test_auto_migrate_disabled_by_default(tmp_path: Path) -> None:
    """Default behaviour: lifespan does NOT create tables. Production-safe."""
    app = create_app(settings=_fresh_settings(tmp_path, auto_migrate=False))
    with TestClient(app) as c:
        # Schema must STILL be missing — confirms via /v1/ready.
        r = c.get("/v1/ready")
    assert r.status_code == 503, r.text
    assert r.json()["checks"]["database"] == "schema_missing"


def test_auto_migrate_creates_schema_when_enabled(tmp_path: Path) -> None:
    """``auto_migrate_on_boot=True`` makes the lifespan call create_all."""
    app = create_app(settings=_fresh_settings(tmp_path, auto_migrate=True))
    with TestClient(app) as c:
        # Schema should exist now — /v1/ready proves it.
        r = c.get("/v1/ready")
    assert r.status_code == 200, r.text
    assert r.json()["checks"]["database"] == "ready"

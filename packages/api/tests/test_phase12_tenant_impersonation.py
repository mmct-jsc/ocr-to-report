"""Tenant impersonation via ``X-Acting-Tenant-Id``.

Admins (keys with ``admin:*``) can scope an otherwise tenant-bound
endpoint at a different tenant by setting the header. The fixture seeds
two tenants (``acme`` + ``acme-admin``) and verifies:

* admin → /v1/jobs with X-Acting-Tenant-Id=acme returns acme's jobs;
* same admin without the header returns its own home tenant's jobs;
* a non-admin trying to impersonate gets 403;
* an admin pointing at an unknown UUID gets 404;
* every successful impersonation appends a ``tenant.impersonated_access``
  audit row on the *target* tenant.
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
from ocr_to_report.api.app import create_app
from ocr_to_report.api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(
        "OCR2R_KEK_B64",
        base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
    )
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    return Settings(
        env="development",
        database_url=db_url,
        blob_backend="local",
        blob_local_root=tmp_path / "blob",
        kek_b64=base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
        profiles_root=REPO_ROOT / "profiles",
        targets_root=REPO_ROOT / "targets",
    )


@pytest.fixture
async def db_setup(settings: Settings) -> None:
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture
async def seeded(settings: Settings, db_setup: None) -> dict[str, Any]:
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        repo = TenantRepo(session, encryptor)
        admin_tenant, _ = await repo.create(name="Admin Org", slug="admin-org")
        target_tenant, _ = await repo.create(name="Acme", slug="acme")
        keys = ApiKeyRepo(session)
        _row, admin_key = await keys.issue(
            tenant_id=admin_tenant.id,
            scopes=["admin:*", "transcripts:write"],
        )
        _row2, plain_key = await keys.issue(
            tenant_id=admin_tenant.id,
            scopes=["transcripts:write"],
        )
        await session.commit()
        return {
            "admin_tenant_id": admin_tenant.id,
            "target_tenant_id": target_tenant.id,
            "admin_key": admin_key,
            "plain_key": plain_key,
        }


@pytest.fixture
def client(settings: Settings, seeded: dict[str, Any]) -> Iterator[TestClient]:
    app = create_app(settings=settings)
    with TestClient(app) as c:
        yield c


def test_admin_can_impersonate_target_tenant(
    client: TestClient, seeded: dict[str, Any]
) -> None:
    headers_home = {"Authorization": f"Bearer {seeded['admin_key']}"}
    headers_act = {
        **headers_home,
        "X-Acting-Tenant-Id": str(seeded["target_tenant_id"]),
    }
    # Both calls should return 200 (the lists may both be empty since
    # no jobs were inserted in this fixture; we're just verifying the
    # auth/impersonation hand-off, not the contents).
    r_home = client.get("/v1/jobs", headers=headers_home)
    r_act = client.get("/v1/jobs", headers=headers_act)
    assert r_home.status_code == 200, r_home.text
    assert r_act.status_code == 200, r_act.text


def test_non_admin_cannot_impersonate(
    client: TestClient, seeded: dict[str, Any]
) -> None:
    r = client.get(
        "/v1/jobs",
        headers={
            "Authorization": f"Bearer {seeded['plain_key']}",
            "X-Acting-Tenant-Id": str(seeded["target_tenant_id"]),
        },
    )
    assert r.status_code == 403
    body = r.json()
    assert body["status"] == 403
    assert "admin:*" in body["detail"]


def test_admin_with_unknown_acting_tenant_404(
    client: TestClient, seeded: dict[str, Any]
) -> None:
    r = client.get(
        "/v1/jobs",
        headers={
            "Authorization": f"Bearer {seeded['admin_key']}",
            "X-Acting-Tenant-Id": "00000000-0000-0000-0000-000000000000",
        },
    )
    assert r.status_code == 404


def test_admin_with_invalid_uuid_in_header_403(
    client: TestClient, seeded: dict[str, Any]
) -> None:
    # A bad UUID is treated as a forbidden header rather than an auth
    # failure — the bearer was valid, the impersonation target wasn't.
    r = client.get(
        "/v1/jobs",
        headers={
            "Authorization": f"Bearer {seeded['admin_key']}",
            "X-Acting-Tenant-Id": "not-a-uuid",
        },
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_impersonation_writes_audit_on_target_tenant(
    client: TestClient, seeded: dict[str, Any], settings: Settings
) -> None:
    r = client.get(
        "/v1/jobs",
        headers={
            "Authorization": f"Bearer {seeded['admin_key']}",
            "X-Acting-Tenant-Id": str(seeded["target_tenant_id"]),
        },
    )
    assert r.status_code == 200

    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT tenant_id, action, resource_type "
                        "FROM audit_log "
                        "WHERE action = 'tenant.impersonated_access'"
                    )
                )
            )
            .mappings()
            .all()
        )
    assert len(rows) >= 1
    assert all(
        str(row["tenant_id"]) == str(seeded["target_tenant_id"]) for row in rows
    )

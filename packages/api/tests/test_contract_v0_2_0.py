"""Schemathesis-driven contract tests for v0.2.0 endpoints.

These run under ``-m contract`` (CI's ci.yml excludes them; the
integration workflow includes them via its own job). Schemathesis
reads the live FastAPI app's OpenAPI schema and fuzzes every operation
under the targeted path filter: it generates parameter / body
combinations consistent with the schema, calls the endpoint, and
asserts the response conforms to the declared response schema. Any
5xx surfaces as a test failure (the API should reject malformed input
with a 4xx, never crash).

We focus this run on the v0.2.0 surfaces specifically:

* ``GET / PUT / POST :preview`` on ``/v1/tenant/config``
* ``POST / DELETE`` on ``/v1/templates/{target_id}/{template_key}``

The Anthropic adapter is mocked out — only the request-routing,
authentication, validation, and persistence layers run.

Why this matters: the v0.2.0 endpoints accept free-form patch dicts.
Hand-written tests cover the happy paths plus a few sad cases;
schemathesis-driven fuzzing finds the combinations a human wouldn't
think to write (empty patches with non-empty op, deeply nested values,
Unicode in path strings, etc).
"""

from __future__ import annotations

import base64
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import schemathesis
from fastapi.testclient import TestClient
from schemathesis import Case
from schemathesis.core.result import Ok

from ocr_to_report.adapters.blob import LocalBlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine, get_sessionmaker
from ocr_to_report.adapters.db.repositories import ApiKeyRepo, TenantRepo
from ocr_to_report.adapters.queue import InMemoryQueue
from ocr_to_report.adapters.vision import (
    FixedPolicy,
    InMemoryAsyncCache,
    ProviderRouter,
    VisionProvider,
)
from ocr_to_report.adapters.vision.stub_adapters import OpenAIVisionAdapter
from ocr_to_report.api.app import create_app
from ocr_to_report.api.deps import AppState
from ocr_to_report.api.settings import Settings
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.sla import SLA_PRESETS
from ocr_to_report.core.targets import TargetRegistry

pytestmark = pytest.mark.contract

REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── fixtures ─────────────────────────────────────────────────────────


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
    """One tenant + api key, transcripts:write scope (covers all v0.2.0 endpoints)."""
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(settings.database_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name="Acme Contract", slug="acme-contract")
        keys = ApiKeyRepo(session)
        _row, plain_key = await keys.issue(tenant_id=tenant.id, scopes=["transcripts:write"])
        await session.commit()
        return {"tenant_id": tenant.id, "api_key": plain_key}


@pytest.fixture
def client_and_seeded(
    settings: Settings, seeded: dict[str, Any]
) -> Iterator[tuple[TestClient, dict[str, Any]]]:
    """A TestClient with the stub Anthropic adapter wired in.

    The transcripts endpoints aren't exercised by these contract tests
    (the schemathesis include filter restricts to /v1/tenant/config +
    /v1/templates/...), but ``create_app`` still expects a usable
    vision router during lifespan setup.
    """
    app = create_app(settings=settings)
    router = ProviderRouter(
        {VisionProvider.OPENAI: OpenAIVisionAdapter()},
        FixedPolicy(VisionProvider.OPENAI),
    )
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())
    bundle_roots = {t.id: settings.targets_root / t.id for t in target_registry.all()}

    test_client = TestClient(app)
    test_client.__enter__()
    app.state.app_state = AppState(
        settings=settings,
        encryptor=encryptor,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=LocalBlobStore(settings.blob_local_root),
        vision_router=router,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
        queue=InMemoryQueue(),
        sla_presets=dict(SLA_PRESETS),
    )
    try:
        yield test_client, seeded
    finally:
        test_client.__exit__(None, None, None)


# ─── the contract test ───────────────────────────────────────────────


def test_v0_2_0_endpoints_conform_to_schema(
    client_and_seeded: tuple[TestClient, dict[str, Any]],
) -> None:
    """Fuzz /v1/tenant/config + /v1/templates/{...} with schemathesis.

    Restricts the operation set with ``.include(path_regex=...)`` so we
    don't burn cycles re-fuzzing the v0.1.0 surfaces (transcripts, jobs,
    admin). Each generated case is invoked against the live ASGI app
    with a valid bearer token; the response is validated against the
    declared OpenAPI schema, and any 5xx fails the test.

    Wraps schemathesis 4.x's ``schema.parametrize()`` pattern via a
    helper loop instead of nesting another @pytest.mark — keeps the
    contract marker on the outer test the only required gate.
    """
    test_client, seeded = client_and_seeded
    app = test_client.app
    headers = {"Authorization": f"Bearer {seeded['api_key']}"}

    # The app mounts its OpenAPI schema under the API_PREFIX, not at
    # the root — see ``api.app.create_app(openapi_url=f"{API_PREFIX}/openapi.json")``.
    schema = schemathesis.openapi.from_asgi(
        "/v1/openapi.json",
        app=app,
    )
    # Restrict to v0.2.0 endpoints. The path_regex is anchored against
    # the OpenAPI path expression (with ``{target_id}`` placeholders),
    # NOT against the resolved URL — so we match by literal substring.
    selected_schema = schema.include(
        path_regex=r"^/v1/tenant/config|^/v1/templates/\{target_id\}/\{template_key\}",
    )

    failures: list[str] = []
    # Hypothesis settings: keep it bounded so this test completes in a
    # reasonable time on every CI run. The intent here is to catch
    # 5xx-class crashes and schema mismatches, not exhaustive
    # property-based exploration — that belongs in a nightly load job.
    max_examples = 25
    operation_count = 0

    for operation_result in selected_schema.get_all_operations():
        if not isinstance(operation_result, Ok):
            # InvalidSchema for some operation — skip; the schema-
            # consistency tests live elsewhere.
            continue
        op = operation_result.ok()
        operation_count += 1
        strategy = op.as_strategy()
        # Hypothesis' .example() draws one input per call; loop to widen
        # coverage while staying deterministic enough for CI.
        for _ in range(max_examples):
            try:
                case: Case = strategy.example()
            except Exception:
                # strategy.example() may fail under contention or when
                # hypothesis exhausts its filter budget. Skip the draw
                # rather than fail the whole contract test.
                continue
            response = case.call(
                session=test_client,
                headers={**headers, **(case.headers or {})},
            )
            try:
                case.validate_response(response)
            except AssertionError as exc:
                failures.append(
                    f"{op.method.upper()} {op.path}: {exc}\n  status={response.status_code}"
                )
            if response.status_code >= 500:
                failures.append(
                    f"{op.method.upper()} {op.path}: HTTP {response.status_code}\n"
                    f"  body={response.text[:300]}"
                )

    # Defensive: if the path filter matched nothing the test passes
    # trivially, which is misleading. Confirm we actually fuzzed the
    # v0.2.0 endpoints (5 ops: GET/PUT tenant/config + POST :preview +
    # POST/DELETE templates).
    assert operation_count >= 4, (
        f"Schemathesis selected {operation_count} operations; expected at least 4 "
        f"(GET/PUT/POST tenant/config + POST/DELETE templates). The include "
        f"filter likely doesn't match the live OpenAPI paths anymore — "
        f"re-check the path_regex in this test."
    )
    assert not failures, (
        "Schemathesis contract violations:\n  "
        + "\n  ".join(failures[:20])
        + (f"\n  ... ({len(failures) - 20} more)" if len(failures) > 20 else "")
    )

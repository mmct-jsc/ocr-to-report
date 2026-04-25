"""Phase 0 — system endpoints work and return the expected shape."""

from __future__ import annotations

from fastapi.testclient import TestClient

from ocr_to_report.api.app import create_app


def _client() -> TestClient:
    return TestClient(create_app())


def test_health_returns_ok() -> None:
    with _client() as c:
        r = c.get("/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_ready_returns_ok_with_checks_object() -> None:
    with _client() as c:
        r = c.get("/v1/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "checks" in body
    assert isinstance(body["checks"], dict)


def test_version_returns_metadata() -> None:
    with _client() as c:
        r = c.get("/v1/version")
    assert r.status_code == 200
    body = r.json()
    assert {"api", "git_sha", "build_time", "python"} <= set(body)
    assert body["api"].startswith("0.1.0")


def test_openapi_published() -> None:
    with _client() as c:
        r = c.get("/v1/openapi.json")
    assert r.status_code == 200
    spec = r.json()
    assert spec["info"]["title"] == "OCR-to-Report"
    paths = spec["paths"]
    assert "/v1/health" in paths
    assert "/v1/ready" in paths
    assert "/v1/version" in paths

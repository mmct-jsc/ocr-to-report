"""CORS middleware — cross-origin browser callers must succeed preflight.

Without CORS configured, a browser on origin A trying to call the API on
origin B issues an ``OPTIONS`` preflight that the FastAPI router rejects
with ``405 Method Not Allowed`` (no OPTIONS handler is registered for the
target route). That makes the SDK unusable from any web page that isn't
served from the same origin as the API — including the common case
where the web Operations Console is shared via one tunnel and the API
through another.

These tests pin the contract:

* By default (no CORS env vars), preflight still fails — production
  default is locked-down.
* When ``OCR2R_CORS_ALLOWED_ORIGINS`` lists the calling origin,
  preflight returns 2xx with the expected ``Access-Control-Allow-*``
  headers.
* When ``OCR2R_CORS_ALLOWED_ORIGIN_REGEX`` matches the calling origin
  (e.g. ``https://.*\\.trycloudflare\\.com``), the same applies — this
  is the tunnel-sharing convenience.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from ocr_to_report.api.app import create_app
from ocr_to_report.api.settings import Settings


def _make_settings(**kwargs: object) -> Settings:
    return Settings(env="development", database_url="sqlite+aiosqlite:///:memory:", **kwargs)


def test_preflight_405_when_cors_unconfigured() -> None:
    """Default behaviour: no CORS, preflight rejected. Same as before this change."""
    app = create_app(settings=_make_settings())
    with TestClient(app) as c:
        r = c.options(
            "/v1/transcripts",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert r.status_code == 405


def test_preflight_succeeds_with_allowed_origin() -> None:
    app = create_app(
        settings=_make_settings(cors_allowed_origins=["https://example.com"]),
    )
    with TestClient(app) as c:
        r = c.options(
            "/v1/transcripts",
            headers={
                "Origin": "https://example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization,content-type",
            },
        )
    assert r.status_code in (200, 204)
    assert r.headers["access-control-allow-origin"] == "https://example.com"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


def test_preflight_rejected_for_origin_not_in_allowlist() -> None:
    app = create_app(
        settings=_make_settings(cors_allowed_origins=["https://example.com"]),
    )
    with TestClient(app) as c:
        r = c.options(
            "/v1/transcripts",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    # Starlette's CORSMiddleware lets the request through to the router
    # when origin isn't allowed — without the Allow-Origin header, the
    # browser blocks it client-side. Verify no Allow-Origin echoed.
    assert "access-control-allow-origin" not in {h.lower() for h in r.headers.keys()}


def test_preflight_succeeds_with_origin_regex() -> None:
    app = create_app(
        settings=_make_settings(
            cors_allowed_origin_regex=r"https://.*\.trycloudflare\.com",
        ),
    )
    with TestClient(app) as c:
        r = c.options(
            "/v1/transcripts",
            headers={
                "Origin": "https://per-passing-notebook-offline.trycloudflare.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "authorization",
            },
        )
    assert r.status_code in (200, 204)
    assert (
        r.headers["access-control-allow-origin"]
        == "https://per-passing-notebook-offline.trycloudflare.com"
    )


def test_actual_request_carries_allow_origin_header() -> None:
    """Even simple GETs need ``Access-Control-Allow-Origin`` set so the
    browser is allowed to read the response body."""
    app = create_app(
        settings=_make_settings(cors_allowed_origins=["https://example.com"]),
    )
    with TestClient(app) as c:
        r = c.get("/v1/health", headers={"Origin": "https://example.com"})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "https://example.com"

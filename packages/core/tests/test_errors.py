"""Error hierarchy + RFC 7807 envelope tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.errors import (
    DependencyError,
    LowConfidenceError,
    NotFoundError,
    OcrToReportError,
    ProblemDetail,
    ProfileNotFoundError,
    UnauthorizedError,
    ValidationError,
    VisionProviderError,
)


# ─── ProblemDetail ─────────────────────────────────────────────
def test_problem_detail_minimal() -> None:
    p = ProblemDetail(title="Bad Request", status=400)
    body = p.to_problem_json()
    assert body == {"type": "about:blank", "title": "Bad Request", "status": 400}


def test_problem_detail_full() -> None:
    p = ProblemDetail(
        type="https://errors/x",
        title="X Error",
        status=422,
        detail="something went wrong",
        instance="urn:job:abc",
        extensions={"job_id": "abc", "field": "name"},
    )
    body = p.to_problem_json()
    assert body == {
        "type": "https://errors/x",
        "title": "X Error",
        "status": 422,
        "detail": "something went wrong",
        "instance": "urn:job:abc",
        "job_id": "abc",
        "field": "name",
    }


def test_problem_detail_extension_collision_with_rfc_keys_is_dropped() -> None:
    p = ProblemDetail(
        title="X",
        status=400,
        extensions={"status": 999, "type": "should-not-leak"},
    )
    body = p.to_problem_json()
    assert body["status"] == 400
    assert body["type"] == "about:blank"


def test_problem_detail_rejects_invalid_status() -> None:
    with pytest.raises(ValueError):
        ProblemDetail(title="X", status=99)
    with pytest.raises(ValueError):
        ProblemDetail(title="X", status=600)


def test_problem_detail_is_frozen() -> None:
    p = ProblemDetail(title="X", status=400)
    with pytest.raises(ValueError):
        p.title = "Y"  # type: ignore[misc]


# ─── Error hierarchy ───────────────────────────────────────────
def test_root_error_default_status() -> None:
    e = OcrToReportError("oops")
    assert e.status == 500
    assert e.detail == "oops"


def test_validation_error_to_problem_detail() -> None:
    e = ValidationError("bad shape", field="name")
    pd = e.to_problem_detail(instance="urn:req:42")
    assert pd.status == 400
    assert pd.title == "Validation failed"
    assert pd.detail == "bad shape"
    assert pd.instance == "urn:req:42"
    assert pd.extensions == {"field": "name"}


def test_specific_subclasses_inherit_status() -> None:
    assert ProfileNotFoundError().status == 404
    assert LowConfidenceError().status == 400
    assert UnauthorizedError().status == 401
    assert VisionProviderError().status == 502


def test_subclass_chain_is_subclass() -> None:
    assert issubclass(ProfileNotFoundError, NotFoundError)
    assert issubclass(VisionProviderError, DependencyError)
    assert issubclass(LowConfidenceError, ValidationError)


def test_default_detail_falls_back_to_title() -> None:
    e = NotFoundError()
    assert e.detail is None
    assert e.to_problem_detail().detail is None


def test_problem_detail_round_trip_via_extensions() -> None:
    e = LowConfidenceError(
        "score 0.42 < threshold 0.85",
        threshold=0.85,
        observed=0.42,
        provider="anthropic-haiku",
    )
    pd = e.to_problem_detail()
    body = pd.to_problem_json()
    assert body["status"] == 400
    assert body["threshold"] == 0.85
    assert body["observed"] == 0.42
    assert body["provider"] == "anthropic-haiku"

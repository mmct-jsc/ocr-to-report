"""Shared utility-type tests."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from ocr_to_report.core.types import (
    PipelineId,
    ProfileId,
    SchemaVersion,
    Sha256Hex,
    TargetId,
    is_valid_pipeline_id,
    is_valid_profile_id,
    is_valid_target_id,
)


class _Wrapper(BaseModel):
    pid: ProfileId
    tid: TargetId
    plid: PipelineId
    ver: SchemaVersion
    h: Sha256Hex


def test_wrapper_accepts_valid_values() -> None:
    w = _Wrapper(
        pid="pl.lo.swiadectwo_szkolne.v1",
        tid="us-hs.v1",
        plid="default_v1",
        ver="1.0",
        h="a" * 64,
    )
    assert w.pid == "pl.lo.swiadectwo_szkolne.v1"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("pid", "PL.LO.x.v1"),  # uppercase
        ("pid", "pl.lo.x"),  # missing .vN
        ("pid", "pl.lo.x.v"),  # vN must have digits
        ("tid", "us hs.v1"),  # space
        ("plid", "Default_v1"),  # uppercase
        ("ver", "1"),  # incomplete version
        ("ver", "1.a"),  # non-numeric
        ("h", "g" * 64),  # not hex
        ("h", "a" * 63),  # wrong length
    ],
)
def test_wrapper_rejects_invalid_values(field: str, value: str) -> None:
    base = {
        "pid": "pl.lo.x.v1",
        "tid": "us-hs.v1",
        "plid": "default_v1",
        "ver": "1.0",
        "h": "a" * 64,
    }
    base[field] = value
    with pytest.raises(ValidationError):
        _Wrapper(**base)


@pytest.mark.parametrize(
    ("validator", "good", "bad"),
    [
        (is_valid_profile_id, "pl.lo.swiadectwo_szkolne.v1", "PL.X.v1"),
        (is_valid_target_id, "us-hs.v1", "US-HS.v1"),
        (is_valid_pipeline_id, "default_v1", "Default_v1"),
    ],
)
def test_validator_helpers(validator: object, good: str, bad: str) -> None:
    assert validator(good) is True  # type: ignore[operator]
    assert validator(bad) is False  # type: ignore[operator]

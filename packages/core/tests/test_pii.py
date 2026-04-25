"""PII classification + redaction tests."""

from __future__ import annotations

import json
from typing import Annotated

import pytest
from pydantic import BaseModel

from ocr_to_report.core.pii import (
    PIIClass,
    field_pii_class,
    get_field_pii_class,
    model_pii_map,
    redact_log_event,
    redacted_dump,
)


class _Sample(BaseModel):
    name: Annotated[str, PIIClass.PII_DIRECT]
    school: Annotated[str, PIIClass.PII_QUASI]
    user_agent: Annotated[str, PIIClass.INTERNAL]
    public_id: str  # no annotation


class _Outer(BaseModel):
    inner: _Sample
    note: Annotated[str, PIIClass.EDUCATIONAL]


# ─── PIIClass enum behaviour ───────────────────────────────────
@pytest.mark.parametrize(
    ("cls", "expected"),
    [
        (PIIClass.PUBLIC, False),
        (PIIClass.INTERNAL, False),
        (PIIClass.PII_QUASI, True),
        (PIIClass.PII_DIRECT, True),
        (PIIClass.EDUCATIONAL, True),
        (PIIClass.SENSITIVE, True),
    ],
)
def test_is_sensitive(cls: PIIClass, expected: bool) -> None:
    assert cls.is_sensitive() is expected


def test_redaction_marker_format() -> None:
    assert PIIClass.PII_DIRECT.redaction_marker() == "[REDACTED:PII_DIRECT]"
    assert PIIClass.SENSITIVE.redaction_marker() == "[REDACTED:SENSITIVE]"


# ─── Annotation reading ────────────────────────────────────────
def test_get_field_pii_class_present() -> None:
    assert get_field_pii_class(_Sample, "name") == PIIClass.PII_DIRECT
    assert get_field_pii_class(_Sample, "school") == PIIClass.PII_QUASI
    assert get_field_pii_class(_Sample, "user_agent") == PIIClass.INTERNAL


def test_get_field_pii_class_absent() -> None:
    assert get_field_pii_class(_Sample, "public_id") is None


def test_get_field_pii_class_unknown_field_raises() -> None:
    with pytest.raises(KeyError):
        get_field_pii_class(_Sample, "no_such_field")


def test_model_pii_map_omits_unannotated() -> None:
    m = model_pii_map(_Sample)
    assert "public_id" not in m
    assert m["name"] == PIIClass.PII_DIRECT


def test_field_pii_class_reflective_fallback() -> None:
    # Same lookup but on a raw Annotated value
    annotated = Annotated[str, PIIClass.SENSITIVE]
    assert field_pii_class(annotated) == PIIClass.SENSITIVE
    assert field_pii_class("plain string") is None


def test_get_field_pii_class_picks_most_sensitive() -> None:
    """When multiple PIIClass values are stacked, the most sensitive wins."""

    class M(BaseModel):
        x: Annotated[str, PIIClass.INTERNAL, PIIClass.PII_DIRECT]

    assert get_field_pii_class(M, "x") == PIIClass.PII_DIRECT


# ─── redacted_dump ─────────────────────────────────────────────
def test_redacted_dump_replaces_sensitive() -> None:
    s = _Sample(
        name="Antoni Judek",
        school="Spark Academy",
        user_agent="curl/8",
        public_id="pid_42",
    )
    out = redacted_dump(s)
    assert out["name"] == PIIClass.PII_DIRECT.redaction_marker()
    assert out["school"] == PIIClass.PII_QUASI.redaction_marker()
    # INTERNAL is not sensitive — stays verbatim
    assert out["user_agent"] == "curl/8"
    assert out["public_id"] == "pid_42"


def test_redacted_dump_keep_overrides() -> None:
    s = _Sample(
        name="Antoni Judek",
        school="Spark Academy",
        user_agent="curl/8",
        public_id="pid_42",
    )
    out = redacted_dump(s, keep=frozenset({PIIClass.PII_DIRECT}))
    # Direct PII kept verbatim
    assert out["name"] == "Antoni Judek"
    # Quasi still redacted
    assert out["school"] == PIIClass.PII_QUASI.redaction_marker()


def test_redacted_dump_recurses_into_nested_model() -> None:
    o = _Outer(
        inner=_Sample(
            name="Antoni Judek",
            school="Spark Academy",
            user_agent="curl/8",
            public_id="pid_42",
        ),
        note="grade detail",
    )
    out = redacted_dump(o)
    assert out["inner"]["name"] == PIIClass.PII_DIRECT.redaction_marker()
    assert out["inner"]["school"] == PIIClass.PII_QUASI.redaction_marker()
    assert out["note"] == PIIClass.EDUCATIONAL.redaction_marker()


def test_redacted_dump_walks_lists() -> None:
    class WithList(BaseModel):
        rows: list[_Sample]

    wl = WithList(
        rows=[
            _Sample(name="A", school="S1", user_agent="u", public_id="p1"),
            _Sample(name="B", school="S2", user_agent="u", public_id="p2"),
        ]
    )
    out = redacted_dump(wl)
    assert out["rows"][0]["name"] == PIIClass.PII_DIRECT.redaction_marker()
    assert out["rows"][1]["school"] == PIIClass.PII_QUASI.redaction_marker()


# ─── structlog processor ───────────────────────────────────────
def test_redact_log_event_processes_models() -> None:
    s = _Sample(
        name="Antoni Judek",
        school="Spark Academy",
        user_agent="curl/8",
        public_id="pid_42",
    )
    event: dict[str, object] = {"event": "process_transcript", "transcript": s}
    out = redact_log_event(None, "info", event)
    assert isinstance(out["transcript"], dict)
    assert out["transcript"]["name"] == PIIClass.PII_DIRECT.redaction_marker()
    assert out["event"] == "process_transcript"


def test_redact_log_event_leaves_plain_strings_alone() -> None:
    """Field names are not redacted in arbitrary user-supplied dicts —
    only model-annotated fields are.
    """
    event = {"event": "ok", "name": "not a model field, do not redact"}
    out = redact_log_event(None, "info", dict(event))
    assert out["name"] == "not a model field, do not redact"


def test_no_pii_value_leaks_to_log_output() -> None:
    """End-to-end completeness check: serialized log output must not contain
    any PII-annotated value verbatim."""
    s = _Sample(
        name="Confidential Person",
        school="Confidential School",
        user_agent="curl/8",
        public_id="pid_42",
    )
    out = redact_log_event(None, "info", {"transcript": s})
    serialized = json.dumps(out)
    assert "Confidential Person" not in serialized
    assert "Confidential School" not in serialized

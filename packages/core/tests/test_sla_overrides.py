"""``core.sla.resolve_with_overrides`` — apply tenant patches to a tier preset.

The override resolver itself shipped in Phase 5 (``core.overrides``);
this module is the thin SLA-specific glue: dump a frozen TenantSlaConfig
in JSON mode, apply the patch list, re-validate through Pydantic. The
re-validation gate is the safety net — out-of-range or unknown-key
patches surface as Pydantic ValidationError that the API maps to 400.
"""

from __future__ import annotations

import copy

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError as PydanticValidationError

from ocr_to_report.core.overrides import OverrideError
from ocr_to_report.core.sla import (
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    resolve_with_overrides,
)


def _standard() -> TenantSlaConfig:
    return SLA_PRESETS[SlaTier.STANDARD]


# ─── Identity / no-op ─────────────────────────────────────────


def test_no_patches_returns_base_directly() -> None:
    """Empty patch list short-circuits and returns ``base`` as-is.

    Frozen Pydantic means the caller can't mutate it whether they hold
    the shared singleton or a fresh clone; returning ``base`` directly
    skips the dump/validate round-trip on the dominant tenant path.
    """
    base = _standard()
    assert resolve_with_overrides(base, []) is base


def test_none_patches_returns_base_directly() -> None:
    """``None`` is treated as empty — same identity short-circuit."""
    base = _standard()
    assert resolve_with_overrides(base, None) is base


# ─── Single-field patch ───────────────────────────────────────


def test_single_set_patch_changes_one_field() -> None:
    """The headline acceptance criterion: raise confidence_threshold."""
    base = _standard()
    resolved = resolve_with_overrides(
        base,
        [{"op": "set", "path": "confidence_threshold", "value": 0.95}],
    )
    assert resolved.confidence_threshold == 0.95
    assert resolved.tier == base.tier
    assert resolved.primary_model == base.primary_model
    assert resolved.retention_days == base.retention_days


def test_tier_override_via_string_value() -> None:
    """C1 regression: enum / Literal fields must accept their public string
    form. Without ``mode='json'`` on the base dump, strict re-validation
    rejected ``"premium"`` because the dump kept ``SlaTier.PREMIUM`` as
    the enum instance and strict mode demanded ``isinstance(SlaTier)``."""
    base = _standard()
    resolved = resolve_with_overrides(
        base,
        [{"op": "set", "path": "tier", "value": "premium"}],
    )
    assert resolved.tier is SlaTier.PREMIUM


def test_provider_policy_override_via_string_value() -> None:
    """Same C1 concern but for ``Literal`` fields (no enum, just string
    constants). ``provider_policy`` switches between known options."""
    base = _standard()
    resolved = resolve_with_overrides(
        base,
        [{"op": "set", "path": "provider_policy", "value": "sonnet_first"}],
    )
    assert resolved.provider_policy == "sonnet_first"


def test_delete_optional_field() -> None:
    """``region_pin: str | None`` defaults to None. A ``delete`` patch on
    a set value must succeed."""
    # Premium has region_pin? No, only explicit overrides set it. Set it
    # then delete it to verify the round-trip.
    base = _standard()
    with_pin = resolve_with_overrides(
        base,
        [{"op": "set", "path": "region_pin", "value": "us-east-1"}],
    )
    without_pin = resolve_with_overrides(
        with_pin,
        [{"op": "delete", "path": "region_pin"}],
    )
    assert without_pin.region_pin is None


# ─── Multi-patch + order ──────────────────────────────────────


def test_multiple_patches_apply_in_order() -> None:
    base = _standard()
    resolved = resolve_with_overrides(
        base,
        [
            {"op": "set", "path": "confidence_threshold", "value": 0.90},
            {"op": "set", "path": "confidence_threshold", "value": 0.95},
            {"op": "set", "path": "park_low_confidence", "value": False},
        ],
    )
    assert resolved.confidence_threshold == 0.95
    assert resolved.park_low_confidence is False


def test_patches_list_is_not_mutated() -> None:
    """The caller's list of dicts is read-only as far as the resolver is
    concerned — important when the same patch list is reused for
    multiple resolutions (cache scenarios)."""
    base = _standard()
    patches = [{"op": "set", "path": "confidence_threshold", "value": 0.95}]
    snapshot = copy.deepcopy(patches)
    resolve_with_overrides(base, patches)
    assert patches == snapshot


# ─── Validation gates ─────────────────────────────────────────


def test_invalid_value_rejected_by_pydantic() -> None:
    """``confidence_threshold`` is ge=0, le=1. 1.5 fails re-validation."""
    base = _standard()
    with pytest.raises(PydanticValidationError):
        resolve_with_overrides(
            base,
            [{"op": "set", "path": "confidence_threshold", "value": 1.5}],
        )


def test_unknown_field_rejected_by_pydantic() -> None:
    """``extra="forbid"`` on the model catches typos."""
    base = _standard()
    with pytest.raises(PydanticValidationError):
        resolve_with_overrides(
            base,
            [{"op": "set", "path": "confidnce_threshold", "value": 0.95}],
        )


def test_invalid_op_surfaces_override_error() -> None:
    """A patch with ``op: "xset"`` (not in OverrideOperation) errors at
    wire-format parse time, before the resolver sees it."""
    base = _standard()
    with pytest.raises(OverrideError):
        resolve_with_overrides(
            base,
            [{"op": "xset", "path": "confidence_threshold", "value": 0.95}],
        )


def test_empty_path_surfaces_override_error() -> None:
    """Empty / whitespace path is caught up front rather than producing
    an opaque ``invalid path segment`` error from the resolver."""
    base = _standard()
    with pytest.raises(OverrideError):
        resolve_with_overrides(
            base,
            [{"op": "set", "path": "   ", "value": 0.95}],
        )


def test_base_config_is_not_mutated() -> None:
    """Frozen Pydantic prevents mutation outright; double-check that
    the JSON dump used internally doesn't leak shared references."""
    base = _standard()
    resolve_with_overrides(
        base,
        [{"op": "set", "path": "confidence_threshold", "value": 0.95}],
    )
    assert base.confidence_threshold == 0.85


def test_premium_tier_override_works_too() -> None:
    """Cross-tier: not just Standard. Premium starts at 0.95; lower it."""
    base = SLA_PRESETS[SlaTier.PREMIUM]
    resolved = resolve_with_overrides(
        base,
        [{"op": "set", "path": "confidence_threshold", "value": 0.90}],
    )
    assert resolved.confidence_threshold == 0.90
    assert resolved.tier == SlaTier.PREMIUM


def test_apply_then_dump_round_trips() -> None:
    """Apply patches, dump the result through JSON, validate again — equal.
    Catches future regressions where round-tripping breaks (e.g., a
    new field that doesn't survive ``model_dump(mode='json')``)."""
    import json as _json

    base = _standard()
    resolved = resolve_with_overrides(
        base,
        [{"op": "set", "path": "confidence_threshold", "value": 0.93}],
    )
    # The JSON path is the one the resolver uses internally — round-trip
    # via the same channel to verify symmetry.
    rehydrated = TenantSlaConfig.model_validate_json(
        _json.dumps(resolved.model_dump(mode="json"))
    )
    assert resolved == rehydrated


# ─── Property test ────────────────────────────────────────────


@given(
    threshold=st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
    park=st.booleans(),
    retention=st.integers(min_value=1, max_value=3650),
)
def test_property_scalar_field_overrides_round_trip(
    threshold: float, park: bool, retention: int
) -> None:
    """For every valid scalar combo, the patched result reflects the
    exact values. Catches regressions on field-by-field plumbing."""
    base = SLA_PRESETS[SlaTier.STANDARD]
    resolved = resolve_with_overrides(
        base,
        [
            {"op": "set", "path": "confidence_threshold", "value": threshold},
            {"op": "set", "path": "park_low_confidence", "value": park},
            {"op": "set", "path": "retention_days", "value": retention},
        ],
    )
    assert resolved.confidence_threshold == threshold
    assert resolved.park_low_confidence is park
    assert resolved.retention_days == retention

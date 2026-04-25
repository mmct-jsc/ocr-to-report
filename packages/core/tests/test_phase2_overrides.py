"""Override resolver tests."""

from __future__ import annotations

import pytest

from ocr_to_report.core.overrides import (
    OverrideError,
    OverrideOperation,
    OverridePatch,
    apply_overrides,
)


# ─── set ───────────────────────────────────────────────────────
def test_set_creates_nested_path() -> None:
    base: dict[str, dict[str, int]] = {"a": {"b": 1}}
    patches = [OverridePatch(path="a.c", operation=OverrideOperation.SET, value=42)]
    result = apply_overrides(base, patches)
    assert result == {"a": {"b": 1, "c": 42}}
    # base unchanged
    assert base == {"a": {"b": 1}}


def test_set_replaces_existing() -> None:
    base = {"a": {"b": 1}}
    patches = [OverridePatch(path="a.b", operation=OverrideOperation.SET, value=2)]
    assert apply_overrides(base, patches) == {"a": {"b": 2}}


def test_set_with_index_lookup() -> None:
    base = {"items": [{"key": "x", "v": 1}, {"key": "y", "v": 2}]}
    patches = [
        OverridePatch(
            path="items[y]",
            operation=OverrideOperation.SET,
            value={"key": "y", "v": 99},
        ),
    ]
    result = apply_overrides(base, patches)
    assert result == {"items": [{"key": "x", "v": 1}, {"key": "y", "v": 99}]}


def test_set_with_numeric_index() -> None:
    base = {"items": ["a", "b", "c"]}
    patches = [OverridePatch(path="items[1]", operation=OverrideOperation.SET, value="B")]
    assert apply_overrides(base, patches) == {"items": ["a", "B", "c"]}


# ─── delete ────────────────────────────────────────────────────
def test_delete_removes_key() -> None:
    base = {"a": 1, "b": 2}
    patches = [OverridePatch(path="b", operation=OverrideOperation.DELETE)]
    assert apply_overrides(base, patches) == {"a": 1}


def test_delete_missing_is_noop() -> None:
    base = {"a": 1}
    patches = [OverridePatch(path="b", operation=OverrideOperation.DELETE)]
    assert apply_overrides(base, patches) == {"a": 1}


def test_delete_list_element_by_key() -> None:
    base = {"items": [{"key": "x", "v": 1}, {"key": "y", "v": 2}]}
    patches = [OverridePatch(path="items[x]", operation=OverrideOperation.DELETE)]
    assert apply_overrides(base, patches) == {"items": [{"key": "y", "v": 2}]}


# ─── append ────────────────────────────────────────────────────
def test_append_to_existing_list() -> None:
    base: dict[str, list[int]] = {"items": [1, 2]}
    patches = [OverridePatch(path="items", operation=OverrideOperation.APPEND, value=3)]
    assert apply_overrides(base, patches) == {"items": [1, 2, 3]}


def test_append_creates_list() -> None:
    base: dict[str, list[str]] = {}
    patches = [OverridePatch(path="items", operation=OverrideOperation.APPEND, value="x")]
    assert apply_overrides(base, patches) == {"items": ["x"]}


# ─── merge ─────────────────────────────────────────────────────
def test_merge_deep_merges_dicts() -> None:
    base = {"a": {"x": 1, "y": 2}}
    patches = [
        OverridePatch(
            path="a",
            operation=OverrideOperation.MERGE,
            value={"y": 99, "z": 3},
        ),
    ]
    assert apply_overrides(base, patches) == {"a": {"x": 1, "y": 99, "z": 3}}


def test_merge_creates_target() -> None:
    base: dict[str, dict[str, dict[str, int]]] = {}
    patches = [
        OverridePatch(path="a.b", operation=OverrideOperation.MERGE, value={"x": 1}),
    ]
    assert apply_overrides(base, patches) == {"a": {"b": {"x": 1}}}


def test_merge_into_list_element_by_key() -> None:
    base = {"items": [{"key": "x", "v": 1, "extra": True}]}
    patches = [
        OverridePatch(
            path="items[x]",
            operation=OverrideOperation.MERGE,
            value={"v": 99},
        ),
    ]
    result = apply_overrides(base, patches)
    assert result == {"items": [{"key": "x", "v": 99, "extra": True}]}


# ─── chains ────────────────────────────────────────────────────
def test_patches_apply_in_order() -> None:
    base = {"x": 1}
    patches = [
        OverridePatch(path="x", operation=OverrideOperation.SET, value=2),
        OverridePatch(path="x", operation=OverrideOperation.SET, value=3),
    ]
    assert apply_overrides(base, patches) == {"x": 3}


# ─── validation ────────────────────────────────────────────────
def test_empty_path_rejected() -> None:
    with pytest.raises(OverrideError):
        OverridePatch(path="", operation=OverrideOperation.DELETE)


def test_append_requires_value() -> None:
    with pytest.raises(OverrideError):
        OverridePatch(path="x", operation=OverrideOperation.APPEND)


def test_merge_requires_dict_value() -> None:
    base: dict[str, dict[str, int]] = {"x": {}}
    patches = [
        OverridePatch(path="x", operation=OverrideOperation.MERGE, value="not a dict"),
    ]
    with pytest.raises(OverrideError):
        apply_overrides(base, patches)


def test_invalid_path_segment_rejected() -> None:
    base = {"x": 1}
    patches = [OverridePatch(path="x..y", operation=OverrideOperation.DELETE)]
    with pytest.raises(OverrideError):
        apply_overrides(base, patches)


def test_lookup_against_non_list_fails() -> None:
    base = {"x": "scalar"}
    patches = [
        OverridePatch(
            path="x[key]",
            operation=OverrideOperation.SET,
            value="new",
        ),
    ]
    with pytest.raises(OverrideError):
        apply_overrides(base, patches)

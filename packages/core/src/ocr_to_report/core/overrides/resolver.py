"""Override patch resolver.

A tenant override is a list of dotted-path patch operations applied to a
base dict (typically the result of ``model.model_dump()`` for a profile or
target bundle). The path syntax is JSON-Pointer-like but uses dots:

    "manifest.name"                   → replace nested key
    "vocabulary.mappings[3].aliases"  → indexed list element
    "templates[grade_9].bindings"     → list element identified by 'key' field

Operations:

* ``set``    — set value at path (creates parents as needed)
* ``delete`` — remove key at path (no-op if missing, by default)
* ``append`` — append to list at path
* ``merge``  — deep-merge a dict into the value at path

This is intentionally narrow: complex schema migrations should ship as a
new profile/target version, not as a stack of overrides.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from ocr_to_report.core.errors.domain import OcrToReportError


class OverrideOperation(StrEnum):
    SET = "set"
    DELETE = "delete"
    APPEND = "append"
    MERGE = "merge"


@dataclass(frozen=True, slots=True)
class OverridePatch:
    """A single override operation."""

    path: str
    operation: OverrideOperation
    value: Any = None

    def __post_init__(self) -> None:
        if not self.path:
            raise OverrideError("override path may not be empty")
        # APPEND and MERGE always require a value. SET may accept value=None
        # (explicit clearing); we don't second-guess that here.
        if (
            self.operation in {OverrideOperation.APPEND, OverrideOperation.MERGE}
            and self.value is None
        ):
            raise OverrideError(
                f"operation {self.operation} requires a value",
                operation=str(self.operation),
            )


class OverrideError(OcrToReportError):
    """A tenant override could not be applied."""

    status = 400
    type_uri = "https://errors.ocr-to-report/override-failed"
    title = "Override failed"


# Match either ``key`` or ``key[index_or_lookup]``
_SEGMENT_RE = re.compile(r"^([^.\[\]]+)(?:\[([^\[\]]+)\])?$")


def apply_overrides(base: Any, patches: list[OverridePatch]) -> Any:
    """Apply a list of patches to ``base`` in order; return a new tree.

    The input is not mutated.
    """
    current = _deep_copy(base)
    for i, patch in enumerate(patches):
        try:
            current = _apply_one(current, patch)
        except OverrideError:
            raise
        except (KeyError, IndexError, TypeError, ValueError) as e:
            raise OverrideError(
                f"patch #{i} ({patch.operation} {patch.path!r}) failed: {e}",
                patch_index=i,
                path=patch.path,
                operation=str(patch.operation),
            ) from e
    return current


def _apply_one(tree: Any, patch: OverridePatch) -> Any:
    segments = _split_path(patch.path)
    if patch.operation is OverrideOperation.SET:
        _set_at(tree, segments, patch.value)
    elif patch.operation is OverrideOperation.DELETE:
        _delete_at(tree, segments)
    elif patch.operation is OverrideOperation.APPEND:
        _append_at(tree, segments, patch.value)
    elif patch.operation is OverrideOperation.MERGE:
        _merge_at(tree, segments, patch.value)
    return tree


def _split_path(path: str) -> list[tuple[str, str | None]]:
    """Split a dotted path into segments. Each segment is ``(name, lookup)``
    where ``lookup`` is the bracketed key (numeric or string) or None."""
    out: list[tuple[str, str | None]] = []
    for raw in path.split("."):
        m = _SEGMENT_RE.match(raw)
        if m is None:
            raise OverrideError(f"invalid path segment: {raw!r}")
        out.append((m.group(1), m.group(2)))
    return out


def _navigate(
    tree: Any,
    segments: list[tuple[str, str | None]],
    *,
    create_missing: bool,
) -> tuple[Any, str | None, str | None]:
    """Traverse to the parent of the target, returning ``(parent, key,
    lookup)`` such that the target is parent[key] or
    parent[key][lookup]."""
    cursor = tree
    for i, (name, lookup) in enumerate(segments[:-1]):
        if not isinstance(cursor, dict):
            raise OverrideError(f"path traversal expected a dict at segment #{i} ({name!r})")
        if name not in cursor:
            if not create_missing:
                raise OverrideError(f"path segment {name!r} not found")
            cursor[name] = {} if lookup is None else []
        sub = cursor[name]
        cursor = sub if lookup is None else _resolve_lookup(sub, lookup)
    last_name, last_lookup = segments[-1]
    if not isinstance(cursor, dict):
        raise OverrideError("path traversal expected a dict at final segment")
    return cursor, last_name, last_lookup


def _resolve_lookup(container: Any, lookup: str) -> Any:
    """Resolve `[lookup]` against a list — either by integer index or by
    matching a `key` field (StrKeyed entries) or `id` field (IdKeyed)."""
    if not isinstance(container, list):
        raise OverrideError(f"cannot index a {type(container).__name__} with [{lookup!r}]")
    if lookup.lstrip("-").isdigit():
        return container[int(lookup)]
    for item in container:
        if isinstance(item, dict) and (item.get("key") == lookup or item.get("id") == lookup):
            return item
    raise OverrideError(f"no list element with key/id {lookup!r}")


def _set_at(tree: Any, segments: list[tuple[str, str | None]], value: Any) -> None:
    parent, name, lookup = _navigate(tree, segments, create_missing=True)
    if lookup is None:
        parent[name] = value
    else:
        if name not in parent:
            parent[name] = []
        target_list = parent[name]
        if not isinstance(target_list, list):
            raise OverrideError(f"{name!r} is not a list")
        if lookup.lstrip("-").isdigit():
            target_list[int(lookup)] = value
        else:
            for i, item in enumerate(target_list):
                if isinstance(item, dict) and (
                    item.get("key") == lookup or item.get("id") == lookup
                ):
                    target_list[i] = value
                    return
            target_list.append(value)


def _delete_at(tree: Any, segments: list[tuple[str, str | None]]) -> None:
    parent, name, lookup = _navigate(tree, segments, create_missing=False)
    if lookup is None:
        parent.pop(name, None)
    else:
        if name not in parent or not isinstance(parent[name], list):
            return
        target_list = parent[name]
        if lookup.lstrip("-").isdigit():
            idx = int(lookup)
            if -len(target_list) <= idx < len(target_list):
                target_list.pop(idx)
        else:
            parent[name] = [
                item
                for item in target_list
                if not (
                    isinstance(item, dict)
                    and (item.get("key") == lookup or item.get("id") == lookup)
                )
            ]


def _append_at(tree: Any, segments: list[tuple[str, str | None]], value: Any) -> None:
    parent, name, lookup = _navigate(tree, segments, create_missing=True)
    if lookup is not None:
        raise OverrideError("append target may not include [lookup]")
    if name not in parent:
        parent[name] = []
    if not isinstance(parent[name], list):
        raise OverrideError(f"append target {name!r} is not a list")
    parent[name].append(value)


def _merge_at(tree: Any, segments: list[tuple[str, str | None]], value: Any) -> None:
    if not isinstance(value, dict):
        raise OverrideError("merge value must be a dict")
    parent, name, lookup = _navigate(tree, segments, create_missing=True)
    if lookup is None:
        if name not in parent:
            parent[name] = {}
        if not isinstance(parent[name], dict):
            raise OverrideError(f"merge target {name!r} is not a dict")
        _deep_merge(parent[name], value)
    else:
        if name not in parent:
            parent[name] = []
        target_list = parent[name]
        if not isinstance(target_list, list):
            raise OverrideError(f"{name!r} is not a list")
        target = _resolve_lookup(target_list, lookup)
        if not isinstance(target, dict):
            raise OverrideError(f"merge target at [{lookup!r}] is not a dict")
        _deep_merge(target, value)


def _deep_merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
    """Recursive in-place dict merge; nested dicts deep-merged, others replaced."""
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = _deep_copy(v)


def _deep_copy(value: Any) -> Any:
    """Shallow-typed deep copy (lists, dicts, primitives only)."""
    if isinstance(value, dict):
        return {k: _deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_deep_copy(v) for v in value]
    return value


__all__ = [
    "OverrideError",
    "OverrideOperation",
    "OverridePatch",
    "apply_overrides",
]

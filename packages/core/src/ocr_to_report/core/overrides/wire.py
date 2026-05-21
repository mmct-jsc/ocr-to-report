"""DB wire format ↔ :class:`OverridePatch` dataclass.

The persistence layer stores patches as ``{op, path, value}`` dicts
matching JSON-Patch conventions; the resolver consumes the typed
:class:`OverridePatch` dataclass form. This module is the single
conversion point so every consumer (SLA resolver today, provider
resolver in v0.3, profile/target resolvers later) shares the same
validation rules.
"""

from __future__ import annotations

from typing import Any

from ocr_to_report.core.overrides.resolver import (
    OverrideError,
    OverrideOperation,
    OverridePatch,
)


def patch_from_wire(raw: dict[str, Any], index: int = 0) -> OverridePatch:
    """Convert one DB-shaped patch dict into an :class:`OverridePatch`.

    Validates ``op`` is one of the known operations, ``path`` is a
    non-empty string, and ``value`` is whatever it is (the resolver
    later type-checks against the destination via Pydantic).

    :raises OverrideError: on invalid ``op`` or empty / non-string ``path``.
    """
    try:
        op = OverrideOperation(raw["op"])
    except (KeyError, ValueError) as e:
        raise OverrideError(
            f"patch #{index} has invalid or missing 'op': {raw.get('op')!r}",
            patch_index=index,
        ) from e
    path = raw.get("path")
    if not isinstance(path, str) or not path.strip():
        raise OverrideError(
            f"patch #{index} has invalid or missing 'path': {path!r}",
            patch_index=index,
        )
    return OverridePatch(path=path, operation=op, value=raw.get("value"))


def patches_from_wire(raws: list[dict[str, Any]]) -> list[OverridePatch]:
    """Convert a list of wire-format dicts, preserving order. Raises on the
    first invalid entry with its index in the error metadata."""
    return [patch_from_wire(p, i) for i, p in enumerate(raws)]


__all__ = ["patch_from_wire", "patches_from_wire"]

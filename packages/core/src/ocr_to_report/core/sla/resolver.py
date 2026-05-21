"""Apply tenant override patches to a tier preset.

``apply_overrides`` shipped in Phase 5 and works on plain dicts. This
module is the SLA-specific glue: dump the frozen ``TenantSlaConfig``
to a JSON-compatible dict, apply patches, re-validate through Pydantic
so out-of-range or unknown-key patches fail before they reach the
worker.

The re-validation honors ``TenantSlaConfig``'s ``strict=True`` +
``extra="forbid"`` config (see ``config.py``). Adding new fields to the
model automatically gets them schema-checked when patched — no resolver
change needed.

Patches arrive in the DB wire format (``{op, path, value}``); the
conversion to :class:`OverridePatch` is delegated to
``core.overrides.patches_from_wire`` so v0.3's provider-config
resolver (and any future resolver) reuses the same parser.
"""

from __future__ import annotations

import json
from typing import Any

from ocr_to_report.core.overrides import apply_overrides, patches_from_wire
from ocr_to_report.core.sla.config import TenantSlaConfig


def resolve_with_overrides(
    base: TenantSlaConfig,
    patches: list[dict[str, Any]] | None,
) -> TenantSlaConfig:
    """Return a ``TenantSlaConfig`` with ``patches`` applied to ``base``.

    The original ``base`` is not mutated. When ``patches`` is empty (or
    ``None``), ``base`` is returned as-is — ``TenantSlaConfig`` is
    ``frozen=True`` so callers cannot mutate it whether they hold a
    fresh instance or the shared singleton, and skipping the
    dump/validate round-trip on the dominant path is a ~10x speedup
    for tenants without any SLA overrides.

    Enum and ``Literal`` fields (``tier``, ``provider_policy``,
    ``audit_detail``) are patched via their public string form (e.g.
    ``"premium"`` for ``SlaTier``); the function dumps the base in
    JSON mode and re-validates from JSON-compatible primitives so the
    strict-mode comparison passes.

    :raises OverrideError: on a malformed patch wire-format entry
        (invalid ``op``, missing or non-string ``path``).
    :raises pydantic.ValidationError: when an otherwise-valid patch
        produces an out-of-range or unknown-key result. The existing
        API exception handler maps this to HTTP 400.
    """
    if patches is None or len(patches) == 0:
        return base

    patch_objs = patches_from_wire(patches)
    # mode='json' dumps enums + Literals to their public string values;
    # model_validate_json then re-parses them with JSON-mode coercion
    # (which converts "premium" -> SlaTier.PREMIUM even under strict
    # mode). Using plain model_validate on the dumped dict would fail
    # because strict mode rejects str-where-enum-expected.
    base_dict = base.model_dump(mode="json")
    result_dict = apply_overrides(base_dict, patch_objs)
    return TenantSlaConfig.model_validate_json(json.dumps(result_dict))


__all__ = ["resolve_with_overrides"]

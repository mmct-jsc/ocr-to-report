"""Shared utility types used across the core domain.

These are deliberately tiny — anything more complex lives in its own module
(e.g., `core/canonical/`, `core/profile/`).
"""

from __future__ import annotations

import re
from typing import Annotated, Final

from pydantic import Field, StringConstraints

# ─── Identifiers ────────────────────────────────────────────────
# Profile / target / pipeline / SLA-tier identifier shape:
#   <namespace>.<name>.<vN>
# Examples: "pl.lo.swiadectwo_szkolne.v1", "us-hs.v1", "default_v1"
_IDENTIFIER_PATTERN: Final = r"^[a-z][a-z0-9_]*(?:[\.\-][a-z0-9_]+)*\.v\d+$"
_SIMPLE_ID_PATTERN: Final = r"^[a-z][a-z0-9_]*(?:_v\d+)?$"

ProfileId = Annotated[
    str,
    StringConstraints(min_length=3, max_length=128, pattern=_IDENTIFIER_PATTERN),
]
"""Source profile bundle id, e.g., `pl.lo.swiadectwo_szkolne.v1`."""

TargetId = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=_IDENTIFIER_PATTERN),
]
"""Target system bundle id, e.g., `us-hs.v1`."""

PipelineId = Annotated[
    str,
    StringConstraints(min_length=3, max_length=64, pattern=_SIMPLE_ID_PATTERN),
]
"""Pipeline id, e.g., `default_v1`."""

SchemaVersion = Annotated[
    str,
    StringConstraints(pattern=r"^\d+\.\d+(?:\.\d+)?$"),
]
"""Schema version string in `MAJOR.MINOR[.PATCH]` form."""


# ─── Hashes & blobs ─────────────────────────────────────────────
Sha256Hex = Annotated[
    str,
    StringConstraints(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64),
]
"""Lower-hex-encoded SHA-256 (64 chars)."""


# ─── Confidence (0..1 inclusive) ────────────────────────────────
Confidence = Annotated[float, Field(ge=0.0, le=1.0)]
"""Normalized confidence score, 0.0 (no confidence) .. 1.0 (full confidence)."""


# ─── Helpers ────────────────────────────────────────────────────
_IDENTIFIER_RE: Final = re.compile(_IDENTIFIER_PATTERN)
_SIMPLE_ID_RE: Final = re.compile(_SIMPLE_ID_PATTERN)


def is_valid_profile_id(value: str) -> bool:
    return bool(_IDENTIFIER_RE.match(value))


def is_valid_target_id(value: str) -> bool:
    return bool(_IDENTIFIER_RE.match(value))


def is_valid_pipeline_id(value: str) -> bool:
    return bool(_SIMPLE_ID_RE.match(value))


__all__ = [
    "Confidence",
    "PipelineId",
    "ProfileId",
    "SchemaVersion",
    "Sha256Hex",
    "TargetId",
    "is_valid_pipeline_id",
    "is_valid_profile_id",
    "is_valid_target_id",
]

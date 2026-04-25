"""Source profile manifest — the top-level descriptor of a profile bundle.

Loaded from ``profiles/<id>/manifest.yaml`` at startup by the registry
introduced in Phase 2.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ocr_to_report.core.types import ProfileId, SchemaVersion, TargetId

# ISO-639-1 two-letter language codes. Conservative regex; if you need
# extended (e.g., zh-Hant) variants in future, evolve this constraint.
LanguageCode = Annotated[
    str,
    StringConstraints(pattern=r"^[a-z]{2}$", min_length=2, max_length=2),
]
"""Two-letter ISO-639-1 language code."""

# Education-system identifier; uppercase ISO-3166-1 alpha-2 by default but
# free-form in case we need IB, A-Levels, etc., as separate systems.
EducationSystemCode = Annotated[
    str,
    StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{1,15}$", max_length=16),
]
"""Education-system identifier (e.g., 'PL', 'VN', 'IB', 'UK_ALEVEL')."""


class ProfileFingerprint(BaseModel):
    """Heuristics for auto-detecting that a document matches this profile.

    The fingerprint runs after preprocessing but before extraction. It is
    intentionally cheap (regex over OCR'd text or filename heuristics) so
    it can be invoked on every upload to choose a profile when the API
    caller did not specify one explicitly.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    header_patterns: list[str] = Field(
        default_factory=list,
        description="Regex patterns expected to match on page 1. Any match "
        "is sufficient (logical OR).",
        max_length=20,
    )
    required_keywords: list[str] = Field(
        default_factory=list,
        description="Whole-word keywords that must ALL appear on page 1 "
        "(logical AND). Case-insensitive.",
        max_length=10,
    )
    min_pages: int = Field(
        default=1,
        ge=1,
        le=20,
        description="Minimum page count for this document type.",
    )
    max_pages: int = Field(
        default=2,
        ge=1,
        le=20,
        description="Maximum page count for this document type.",
    )

    def model_post_init(self, _ctx: object, /) -> None:
        if self.max_pages < self.min_pages:
            raise ValueError("max_pages must be ≥ min_pages")


class ProfileManifest(BaseModel):
    """Top-level metadata for a source profile bundle."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: ProfileId = Field(
        description="Globally unique profile id.",
    )
    name: str = Field(
        min_length=1,
        max_length=200,
        description="Human-readable profile name.",
    )
    description: str | None = Field(
        default=None,
        max_length=1000,
        description="Longer description of what this profile handles.",
    )
    version: SchemaVersion = Field(
        description="Bundle version (semver-ish: MAJOR.MINOR[.PATCH]).",
    )
    source_language: LanguageCode = Field(
        description="Primary language of the source document.",
    )
    education_system: EducationSystemCode = Field(
        description="Education-system code this profile applies to.",
    )
    document_type: Annotated[
        str,
        StringConstraints(pattern=r"^[a-z][a-z0-9_]*$", min_length=1, max_length=64),
    ] = Field(
        description="Slug describing the document family "
        "(e.g., 'school_certificate', 'grade_report').",
    )
    fingerprint: ProfileFingerprint = Field(
        description="Auto-detection rules for this document type.",
    )
    default_target_systems: list[TargetId] = Field(
        default_factory=list,
        description="Target system bundle ids this profile is most often "
        "paired with. Ordered by relevance.",
        max_length=10,
    )


__all__ = [
    "EducationSystemCode",
    "LanguageCode",
    "ProfileFingerprint",
    "ProfileManifest",
]

"""Target system manifest — the top-level descriptor of a target bundle."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from ocr_to_report.core.profile.manifest import EducationSystemCode, LanguageCode
from ocr_to_report.core.types import SchemaVersion, TargetId


class TargetManifest(BaseModel):
    """Top-level metadata for a target system bundle.

    A target system is the destination of a transcript conversion (US high
    school, US college GPA, UK UCAS, IB Diploma, etc.). Each ships its own
    grade scale, year system, subject taxonomy, and templates.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    id: TargetId = Field(description="Globally unique target system id.")
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=1000)
    version: SchemaVersion

    output_language: LanguageCode = Field(
        description="Language used for display strings in templates.",
    )
    education_system: EducationSystemCode = Field(
        description="Education-system code this target belongs to.",
    )
    output_formats: list[
        Annotated[
            str,
            StringConstraints(pattern=r"^(xlsx|pdf|csv|docx|json)$", min_length=3, max_length=5),
        ]
    ] = Field(
        default_factory=lambda: ["xlsx"],
        min_length=1,
        description="Supported output formats for this target.",
    )


__all__ = ["TargetManifest"]

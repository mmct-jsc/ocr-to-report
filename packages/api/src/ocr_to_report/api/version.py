"""Build/runtime version metadata exposed via /v1/version."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from ocr_to_report.api import __version__ as api_version


@dataclass(frozen=True, slots=True)
class VersionInfo:
    api: str
    git_sha: str
    build_time: str
    python: str

    def to_dict(self) -> dict[str, str]:
        return {
            "api": self.api,
            "git_sha": self.git_sha,
            "build_time": self.build_time,
            "python": self.python,
        }


def get_version_info() -> VersionInfo:
    return VersionInfo(
        api=api_version,
        git_sha=os.getenv("OCR2R_GIT_SHA", "dev"),
        build_time=os.getenv("OCR2R_BUILD_TIME", "dev"),
        python=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )

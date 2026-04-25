"""Shared worker fixtures."""

from __future__ import annotations

import base64
import io
import secrets
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from PIL import Image as PILImage

from ocr_to_report.adapters.crypto.envelope import DEK_BYTES
from ocr_to_report.adapters.db import Base, get_engine
from ocr_to_report.api.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def png_bytes() -> bytes:
    """Tiny PNG suitable for preprocess/extract pipelines."""
    img = PILImage.new("RGB", (400, 600), color=(220, 220, 220))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv(
        "OCR2R_KEK_B64",
        base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
    )
    db_url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    return Settings(
        env="development",
        database_url=db_url,
        blob_backend="local",
        blob_local_root=tmp_path / "blob",
        kek_b64=base64.b64encode(secrets.token_bytes(DEK_BYTES)).decode(),
        profiles_root=REPO_ROOT / "profiles",
        targets_root=REPO_ROOT / "targets",
    )


@pytest.fixture
async def db_setup(settings: Settings) -> AsyncIterator[None]:
    engine = get_engine(settings.database_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


@pytest.fixture
def db_metadata_initialized(settings: Settings) -> Any:
    """Force imports of all model classes so metadata is complete."""
    from ocr_to_report.adapters.db import models  # noqa: PLC0415

    return models

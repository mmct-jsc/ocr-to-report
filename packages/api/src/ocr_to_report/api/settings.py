"""Pydantic-settings application configuration.

12-factor: every knob is read from an environment variable with the
``OCR2R_`` prefix. ``.env`` is read in development; in production the
deployment platform injects the env directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration."""

    model_config = SettingsConfigDict(
        env_prefix="OCR2R_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ─── Environment ──────────────────────────────────────────
    env: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ─── Server ───────────────────────────────────────────────
    api_host: str = Field(default="0.0.0.0")  # noqa: S104 — containerized
    api_port: int = 8000
    api_workers: int = 1

    # ─── Database ─────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///:memory:"

    # ─── Blob storage ─────────────────────────────────────────
    blob_backend: Literal["local", "s3"] = "local"
    blob_local_root: Path = Field(default=Path("./.local-blob"))
    blob_endpoint_url: str | None = None
    blob_bucket: str = "ocr2r"
    blob_access_key: str | None = None
    blob_secret_key: str | None = None
    blob_region: str = "us-east-1"

    # ─── Crypto ───────────────────────────────────────────────
    kek_b64: str | None = None
    """Master KEK as base64-encoded 32 bytes; required for encryption."""

    # ─── Bundles + pipelines on disk ──────────────────────────
    profiles_root: Path = Field(default=Path("./profiles"))
    targets_root: Path = Field(default=Path("./targets"))
    pipelines_root: Path = Field(default=Path("./pipelines"))
    sla_tiers_root: Path = Field(default=Path("./sla-tiers"))

    # ─── Anthropic ────────────────────────────────────────────
    anthropic_api_key: str | None = Field(
        default=None,
        validation_alias="ANTHROPIC_API_KEY",
    )

    # ─── Idempotency / replay ─────────────────────────────────
    idempotency_ttl_seconds: int = 24 * 60 * 60
    """How long replayed responses are cached. 24h is the OCR-to-Report default."""

    # ─── File upload limits ───────────────────────────────────
    max_upload_bytes: int = 25 * 1024 * 1024
    """Maximum size of an uploaded transcript blob (25 MiB)."""

    # ─── CORS ────────────────────────────────────────────────
    cors_allowed_origins: list[str] = Field(default_factory=list)
    """Origins permitted by the browser CORS check.

    Empty (the default) means CORS middleware is **not installed** and
    cross-origin browser callers receive a ``405`` on their ``OPTIONS``
    preflight — same shape as a same-origin-only deployment.

    Set this when the API is exposed on a different origin from the
    web console (e.g. when both are tunneled separately for sharing,
    or when an external SDK consumer hosts a page on its own domain).
    """

    cors_allowed_origin_regex: str | None = None
    """Regex alternative for ``cors_allowed_origins``.

    Useful for tunnel/dev environments where the public hostname is
    randomized — e.g. ``https://.*\\.trycloudflare\\.com`` whitelists
    every Cloudflare quick-tunnel URL without listing them by hand.
    """

    # ─── Build metadata ───────────────────────────────────────
    git_sha: str = "dev"
    build_time: str = "dev"


def load_settings() -> Settings:
    """Construct settings; useful as a FastAPI dependency."""
    return Settings()


__all__ = ["Settings", "load_settings"]

"""MCP tool registration.

Builds a :class:`mcp.server.fastmcp.FastMCP` instance with one tool per
public API operation. Each tool delegates to the SDK and returns the
SDK's Pydantic model dumped to a JSON-compatible dict so MCP clients
get structured output.
"""

from __future__ import annotations

import os
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from ocr_to_report.sdk_py import Client

_DEFAULT_SERVER_NAME = "ocr-to-report"


def _client() -> Client:
    """Build a sync :class:`Client` from environment variables.

    A fresh client is constructed per tool call. That's fine for stdio
    MCP — tool invocations are sequential and short-lived, and httpx
    connection pooling is per-instance — but the function is the
    natural seam for a future shared-client refactor.
    """
    base_url = os.environ.get("OCR2R_BASE_URL", "http://localhost:8000")
    api_key = os.environ.get("OCR2R_API_KEY")
    if not api_key:
        raise RuntimeError("OCR2R_API_KEY is unset; set it in the MCP server's environment")
    return Client(base_url=base_url, api_key=api_key)


def _dump(model: Any) -> Any:
    """Pydantic → JSON-compatible dict (or pass-through for primitives)."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


def build_server(name: str = _DEFAULT_SERVER_NAME) -> FastMCP:
    """Construct a FastMCP server with every operation registered."""
    server = FastMCP(name)

    @server.tool(
        description=(
            "Synchronously extract + render a single transcript file. "
            "The file_path must point to a PDF/PNG/JPEG on the host."
        ),
    )
    def process_transcript(
        file_path: str,
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"file does not exist: {file_path}")
        with _client() as c:
            response = c.transcripts.create(
                file_bytes=path.read_bytes(),
                filename=path.name,
                profile_id=profile_id,
                target_id=target_id,
                target_template_key=target_template_key,
                content_type=_guess_content_type(path),
            )
            return dict(_dump(response))

    @server.tool(
        description=(
            "Submit a list of transcript files via the batch endpoint. "
            "Returns immediately with per-job summaries; results are "
            "delivered via webhook or polled via get_job."
        ),
    )
    def submit_batch(
        file_paths: list[str],
        profile_id: str,
        target_id: str,
        target_template_key: str | None = None,
    ) -> dict[str, Any]:
        files: list[tuple[str, bytes, str]] = []
        for raw in file_paths:
            path = Path(raw)
            if not path.is_file():
                raise FileNotFoundError(f"file does not exist: {raw}")
            files.append((path.name, path.read_bytes(), _guess_content_type(path)))
        with _client() as c:
            response = c.transcripts.create_batch(
                files=files,
                profile_id=profile_id,
                target_id=target_id,
                target_template_key=target_template_key,
            )
            return dict(_dump(response))

    @server.tool(description="Fetch a single job by id.")
    def get_job(job_id: str) -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.jobs.get(uuid.UUID(job_id))))

    @server.tool(
        description=(
            "List jobs for the current tenant. Use status='parked' to "
            "see jobs awaiting manual review."
        ),
    )
    def list_jobs(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        with _client() as c:
            return [dict(_dump(j)) for j in c.jobs.list(status=status, limit=limit)]

    @server.tool(
        description=(
            "Approve a parked job (re-extract with stronger model, "
            "complete pipeline, render output)."
        ),
    )
    def approve_job(job_id: str) -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.jobs.approve(uuid.UUID(job_id))))

    @server.tool(description="Reject a parked job; mark it failed.")
    def reject_job(job_id: str, reason: str | None = None) -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.jobs.reject(uuid.UUID(job_id), reason=reason)))

    @server.tool(description="List available target systems + their templates.")
    def list_templates() -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.templates.list()))

    @server.tool(description="Get the current period's token + cost rollup for the tenant.")
    def get_usage() -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.usage.get()))

    @server.tool(
        description=(
            "Create a new webhook subscription. The signing_secret is "
            "ONLY returned here; store it before exiting."
        ),
    )
    def create_webhook(url: str, events: list[str]) -> dict[str, Any]:
        with _client() as c:
            return dict(_dump(c.webhooks.create(url=url, events=events)))

    @server.tool(description="List webhook subscriptions (without signing secrets).")
    def list_webhooks() -> list[dict[str, Any]]:
        with _client() as c:
            return [dict(_dump(w)) for w in c.webhooks.list()]

    return server


def _guess_content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".tiff": "image/tiff",
        ".tif": "image/tiff",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")


__all__ = ["build_server"]

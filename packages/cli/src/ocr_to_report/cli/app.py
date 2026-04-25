"""Typer command tree.

Every subcommand is a thin wrapper around the SDK. Output is JSON by
default (machine-readable for piping); ``--pretty`` switches to a
Rich-rendered view for humans.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from ocr_to_report.sdk_py import Client, SDKError

app = typer.Typer(
    name="ocr-to-report",
    help="OCR-to-Report CLI — interact with the v1 REST API.",
    no_args_is_help=True,
    add_completion=False,
)

jobs_app = typer.Typer(name="jobs", help="Inspect, approve, reject, fetch jobs.")
webhooks_app = typer.Typer(name="webhooks", help="Manage webhook subscriptions.")
app.add_typer(jobs_app, name="jobs")
app.add_typer(webhooks_app, name="webhooks")

_console = Console()
_err_console = Console(stderr=True, style="red")


# ─── Shared options ──────────────────────────────────────────
def _client(base_url: str | None, api_key: str | None) -> Client:
    """Build a Client honoring CLI overrides + env-var defaults."""
    resolved_base = base_url or os.environ.get("OCR2R_BASE_URL", "http://localhost:8000")
    resolved_key = api_key or os.environ.get("OCR2R_API_KEY")
    if not resolved_key:
        _err_console.print(
            "missing API key: pass --api-key or set OCR2R_API_KEY",
        )
        raise typer.Exit(code=2)
    return Client(base_url=resolved_base, api_key=resolved_key)


def _emit(payload: Any, *, pretty: bool) -> None:
    """JSON to stdout by default; rich when ``pretty`` is requested."""
    if pretty:
        _console.print_json(data=payload)
    else:
        sys.stdout.write(json.dumps(payload, default=str))
        sys.stdout.write("\n")


def _to_dict(model: Any) -> Any:
    """Convert a Pydantic model to JSON-serializable dict (mode='json')."""
    if hasattr(model, "model_dump"):
        return model.model_dump(mode="json")
    return model


# ─── process ─────────────────────────────────────────────────
@app.command()
def process(
    file: Annotated[Path, typer.Argument(exists=True, readable=True, dir_okay=False)],
    profile_id: Annotated[str, typer.Option("--profile", help="Source profile id")],
    target_id: Annotated[str, typer.Option("--target", help="Target system id")],
    target_template_key: Annotated[
        str | None,
        typer.Option("--template", help="Optional target template key"),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="If set, download the rendered xlsx to this path on success.",
        ),
    ] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty", help="Rich-rendered output")] = False,
) -> None:
    """Sync extract + render a single transcript."""
    client = _client(base_url, api_key)
    try:
        with client:
            blob = file.read_bytes()
            response = client.transcripts.create(
                file_bytes=blob,
                filename=file.name,
                profile_id=profile_id,
                target_id=target_id,
                target_template_key=target_template_key,
                content_type=_guess_content_type(file),
            )
            _emit(_to_dict(response), pretty=pretty)
            if output is not None and response.job.status == "succeeded":
                rendered = client.jobs.get_result(response.job.id)
                output.write_bytes(rendered)
                _err_console.print(f"wrote {len(rendered)} bytes to {output}", style="green")
    except SDKError as e:
        _exit_with_error(e)


# ─── batch ───────────────────────────────────────────────────
@app.command()
def batch(
    files: Annotated[
        list[Path],
        typer.Argument(exists=True, readable=True, dir_okay=False),
    ],
    profile_id: Annotated[str, typer.Option("--profile", help="Source profile id")],
    target_id: Annotated[str, typer.Option("--target", help="Target system id")],
    target_template_key: Annotated[
        str | None,
        typer.Option("--template", help="Optional target template key"),
    ] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """Submit a list of files via POST /v1/transcripts:batch."""
    client = _client(base_url, api_key)
    payload = [(f.name, f.read_bytes(), _guess_content_type(f)) for f in files]
    try:
        with client:
            response = client.transcripts.create_batch(
                files=payload,
                profile_id=profile_id,
                target_id=target_id,
                target_template_key=target_template_key,
            )
            _emit(_to_dict(response), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


# ─── jobs ────────────────────────────────────────────────────
@jobs_app.command("get")
def jobs_get(
    job_id: Annotated[uuid.UUID, typer.Argument(help="Job UUID")],
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    client = _client(base_url, api_key)
    try:
        with client:
            job = client.jobs.get(job_id)
            _emit(_to_dict(job), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


@jobs_app.command("list")
def jobs_list(
    status: Annotated[
        str | None,
        typer.Option("--status", help="Filter by status (e.g., 'parked')."),
    ] = None,
    limit: Annotated[int, typer.Option("--limit", min=1, max=500)] = 100,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """List recent jobs (optionally filtered by status)."""
    client = _client(base_url, api_key)
    try:
        with client:
            jobs = client.jobs.list(status=status, limit=limit)
            if pretty:
                _print_jobs_table(jobs)
            else:
                _emit([_to_dict(j) for j in jobs], pretty=False)
    except SDKError as e:
        _exit_with_error(e)


@jobs_app.command("approve")
def jobs_approve(
    job_id: Annotated[uuid.UUID, typer.Argument(help="Parked job UUID")],
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """Approve a parked job (re-extract + complete)."""
    client = _client(base_url, api_key)
    try:
        with client:
            job = client.jobs.approve(job_id)
            _emit(_to_dict(job), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


@jobs_app.command("reject")
def jobs_reject(
    job_id: Annotated[uuid.UUID, typer.Argument(help="Parked job UUID")],
    reason: Annotated[
        str | None,
        typer.Option("--reason", help="Why the job was rejected."),
    ] = None,
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """Reject a parked job (mark failed)."""
    client = _client(base_url, api_key)
    try:
        with client:
            job = client.jobs.reject(job_id, reason=reason)
            _emit(_to_dict(job), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


@jobs_app.command("result")
def jobs_result(
    job_id: Annotated[uuid.UUID, typer.Argument(help="Job UUID")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Write the xlsx blob to this path."),
    ],
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
) -> None:
    """Download the rendered xlsx for a succeeded job."""
    client = _client(base_url, api_key)
    try:
        with client:
            blob = client.jobs.get_result(job_id)
            output.write_bytes(blob)
            _err_console.print(f"wrote {len(blob)} bytes to {output}", style="green")
    except SDKError as e:
        _exit_with_error(e)


# ─── webhooks ────────────────────────────────────────────────
@webhooks_app.command("create")
def webhooks_create(
    url: Annotated[str, typer.Option("--url", help="Webhook receiver URL")],
    events: Annotated[
        list[str],
        typer.Option("--event", "-e", help="Event type to subscribe to (repeatable)."),
    ],
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """Create a new webhook subscription."""
    client = _client(base_url, api_key)
    try:
        with client:
            created = client.webhooks.create(url=url, events=events)
            _emit(_to_dict(created), pretty=pretty)
            _err_console.print(
                "store signing_secret immediately — it is not retrievable later",
                style="yellow",
            )
    except SDKError as e:
        _exit_with_error(e)


@webhooks_app.command("list")
def webhooks_list(
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    client = _client(base_url, api_key)
    try:
        with client:
            rows = client.webhooks.list()
            _emit([_to_dict(r) for r in rows], pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


# ─── usage / templates ───────────────────────────────────────
@app.command()
def usage(
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """Current-period token + cost rollup."""
    client = _client(base_url, api_key)
    try:
        with client:
            data = client.usage.get()
            _emit(_to_dict(data), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


@app.command()
def templates(
    base_url: Annotated[str | None, typer.Option("--base-url")] = None,
    api_key: Annotated[str | None, typer.Option("--api-key")] = None,
    pretty: Annotated[bool, typer.Option("--pretty")] = False,
) -> None:
    """List available target systems + their templates."""
    client = _client(base_url, api_key)
    try:
        with client:
            data = client.templates.list()
            _emit(_to_dict(data), pretty=pretty)
    except SDKError as e:
        _exit_with_error(e)


# ─── version ─────────────────────────────────────────────────
@app.command()
def version() -> None:
    """Print the CLI version."""
    from ocr_to_report.cli import __version__  # noqa: PLC0415

    typer.echo(f"ocr-to-report {__version__}")


# ─── helpers ─────────────────────────────────────────────────
def _print_jobs_table(jobs: list[Any]) -> None:
    table = Table(title="Jobs", show_lines=False)
    for col in ("id", "status", "profile", "target", "tokens", "cost", "created"):
        table.add_column(col)
    for j in jobs:
        table.add_row(
            str(j.id),
            j.status,
            j.profile_id or "-",
            j.target_id or "-",
            f"{j.tokens_input}/{j.tokens_output}",
            f"${j.usd_cost:.4f}",
            j.created_at.isoformat() if hasattr(j.created_at, "isoformat") else str(j.created_at),
        )
    _console.print(table)


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


def _exit_with_error(error: SDKError) -> None:
    _err_console.print(f"error: {error}")
    if error.body:
        _err_console.print(json.dumps(error.body))
    raise typer.Exit(code=1)


__all__ = ["app"]

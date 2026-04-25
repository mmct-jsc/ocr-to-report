"""Phase 9 — CLI command-tree smoke tests.

Drives Typer's :class:`CliRunner` against the full app. The SDK calls
are stubbed at the ``Client`` boundary so we don't need a running
server — these tests verify the CLI's argument parsing, output shape,
and error handling.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from ocr_to_report.cli.app import app
from ocr_to_report.sdk_py import (
    BatchAcceptedResponse,
    JobSummary,
    SDKError,
    TemplateInfo,
    TemplatesResponse,
    TranscriptExtractionResponse,
    UsageResponse,
    WebhookCreateResponse,
    WebhookSummary,
)
from ocr_to_report.sdk_py.models import TargetInfo

runner = CliRunner()


def _job_summary(status: str = "succeeded") -> JobSummary:
    now = datetime.now(tz=UTC)
    return JobSummary(
        id=uuid.uuid4(),
        status=status,
        profile_id="pl.lo.swiadectwo_szkolne.v1",
        target_id="us-hs.v1",
        target_template_key=None,
        pipeline_id="default_v1",
        provider_used="anthropic",
        model_id_used="claude-haiku-4-5",
        tokens_input=1500,
        tokens_output=300,
        usd_cost=0.003,
        error_detail=None,
        park_reason=None,
        output_blob_key="jobs/x/output.xlsx",
        created_at=now,
        updated_at=now,
        completed_at=now,
        expires_at=None,
    )


def _stub_client() -> Any:
    """Build a MagicMock that quacks like a Client + nested resources."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=None)
    return client


def test_version_command() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "ocr-to-report" in result.stdout


def test_process_uses_sdk_and_emits_json(tmp_path: Path) -> None:
    file = tmp_path / "t.png"
    file.write_bytes(b"\x89PNG\r\nfake")

    fake = _stub_client()
    job = _job_summary("succeeded")
    fake.transcripts.create.return_value = TranscriptExtractionResponse(
        job=job,
        extraction={"student": {"full_name": "Jan"}},
        overall_confidence=0.95,
        warnings=[],
    )
    fake.jobs.get_result.return_value = b"PK\x03\x04xlsx-bytes"

    output_path = tmp_path / "out.xlsx"
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            [
                "process",
                str(file),
                "--profile",
                "pl.lo.swiadectwo_szkolne.v1",
                "--target",
                "us-hs.v1",
                "--output",
                str(output_path),
                "--api-key",
                "sk_test",
            ],
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["job"]["status"] == "succeeded"
    assert output_path.read_bytes() == b"PK\x03\x04xlsx-bytes"
    fake.transcripts.create.assert_called_once()


def test_process_missing_api_key_exits_2(tmp_path: Path) -> None:
    file = tmp_path / "t.png"
    file.write_bytes(b"x")
    # Make sure env var is unset.
    result = runner.invoke(
        app,
        [
            "process",
            str(file),
            "--profile",
            "p",
            "--target",
            "t",
        ],
        env={"OCR2R_API_KEY": "", "OCR2R_BASE_URL": "http://x"},
    )
    assert result.exit_code == 2


def test_batch_command(tmp_path: Path) -> None:
    file_a = tmp_path / "a.png"
    file_b = tmp_path / "b.png"
    file_a.write_bytes(b"a")
    file_b.write_bytes(b"b")

    fake = _stub_client()
    fake.transcripts.create_batch.return_value = BatchAcceptedResponse(
        jobs=[_job_summary("pending"), _job_summary("pending")],
        accepted_count=2,
        rejected=[],
    )

    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            [
                "batch",
                str(file_a),
                str(file_b),
                "--profile",
                "pl.lo.swiadectwo_szkolne.v1",
                "--target",
                "us-hs.v1",
                "--api-key",
                "sk_test",
            ],
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["accepted_count"] == 2


def test_jobs_get(tmp_path: Path) -> None:
    fake = _stub_client()
    fake.jobs.get.return_value = _job_summary("succeeded")
    job_id = uuid.uuid4()
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            ["jobs", "get", str(job_id), "--api-key", "sk_test"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "succeeded"


def test_jobs_list_with_status_filter() -> None:
    fake = _stub_client()
    fake.jobs.list.return_value = [_job_summary("parked")]
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            ["jobs", "list", "--status", "parked", "--api-key", "sk_test"],
        )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    assert payload[0]["status"] == "parked"
    fake.jobs.list.assert_called_once_with(status="parked", limit=100)


def test_jobs_approve() -> None:
    fake = _stub_client()
    fake.jobs.approve.return_value = _job_summary("succeeded")
    job_id = uuid.uuid4()
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            ["jobs", "approve", str(job_id), "--api-key", "sk_test"],
        )
    assert result.exit_code == 0
    fake.jobs.approve.assert_called_once_with(job_id)


def test_jobs_reject_with_reason() -> None:
    fake = _stub_client()
    fake.jobs.reject.return_value = _job_summary("failed")
    job_id = uuid.uuid4()
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            [
                "jobs",
                "reject",
                str(job_id),
                "--reason",
                "blurry",
                "--api-key",
                "sk_test",
            ],
        )
    assert result.exit_code == 0
    fake.jobs.reject.assert_called_once_with(job_id, reason="blurry")


def test_templates_command() -> None:
    fake = _stub_client()
    fake.templates.list.return_value = TemplatesResponse(
        targets=[
            TargetInfo(
                target_id="us-hs.v1",
                name="US High School",
                version="1.0",
                output_language="en",
                output_formats=["xlsx"],
                templates=[
                    TemplateInfo(key="grade_9", output_format="xlsx", target_year_index=0),
                ],
            ),
        ],
    )
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(app, ["templates", "--api-key", "sk_test"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["targets"][0]["target_id"] == "us-hs.v1"


def test_usage_command() -> None:
    fake = _stub_client()
    now = datetime.now(tz=UTC)
    fake.usage.get.return_value = UsageResponse(
        period_start=now,
        period_end=now,
        transcripts_processed=5,
        tokens_input=10000,
        tokens_output=2000,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        usd_cost=0.05,
    )
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(app, ["usage", "--api-key", "sk_test"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["transcripts_processed"] == 5


def test_webhooks_create_warns_about_secret() -> None:
    fake = _stub_client()
    fake.webhooks.create.return_value = WebhookCreateResponse(
        id=uuid.uuid4(),
        url="https://example.com/hook",
        events=["job.completed"],
        active=True,
        signing_secret="0" * 64,
    )
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            [
                "webhooks",
                "create",
                "--url",
                "https://example.com/hook",
                "-e",
                "job.completed",
                "--api-key",
                "sk_test",
            ],
        )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["signing_secret"] == "0" * 64


def test_webhooks_list() -> None:
    fake = _stub_client()
    fake.webhooks.list.return_value = [
        WebhookSummary(
            id=uuid.uuid4(),
            url="https://example.com/hook",
            events=["job.completed"],
            active=True,
            last_delivery_status=None,
            last_delivered_at=None,
        ),
    ]
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(app, ["webhooks", "list", "--api-key", "sk_test"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert len(payload) == 1


def test_sdk_error_results_in_exit_1() -> None:
    fake = _stub_client()
    fake.jobs.get.side_effect = SDKError("not found", status=404, body={"detail": "no such job"})
    with patch("ocr_to_report.cli.app.Client", return_value=fake):
        result = runner.invoke(
            app,
            ["jobs", "get", str(uuid.uuid4()), "--api-key", "sk_test"],
        )
    assert result.exit_code == 1

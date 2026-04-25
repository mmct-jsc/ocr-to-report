"""Phase 10 — SLO + alert rule sanity checks.

We don't run a real Prometheus to validate the rules; that's overkill
for unit scope. Instead, we lint the YAML for the structural shape
``promtool check rules`` enforces:

* Top-level ``groups`` list.
* Each group has ``name`` + ``rules``.
* Each rule has ``alert`` + ``expr`` + ``labels.severity`` +
  ``annotations.summary``.
* Every metric name referenced in an alert exists in our
  :class:`Metrics` namespace (= no typos drifting from code).

Cheap, deterministic, and catches the bugs that actually slip through.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from ocr_to_report.api.metrics import build_metrics

REPO_ROOT = Path(__file__).resolve().parents[3]
ALERTS_PATH = REPO_ROOT / "observability" / "prometheus_alerts.yaml"
DASHBOARD_PATH = REPO_ROOT / "observability" / "grafana_dashboard.json"


def _load_alerts() -> dict[str, Any]:
    return dict(yaml.safe_load(ALERTS_PATH.read_text(encoding="utf-8")))


def _declared_metric_names() -> set[str]:
    """Names of the Counters/Gauges/Histograms we expose."""
    metrics = build_metrics()
    out: set[str] = set()
    for collector in (
        metrics.http_requests_total,
        metrics.http_request_duration_seconds,
        metrics.http_errors_total,
        metrics.pipeline_step_duration_seconds,
        metrics.vision_confidence,
        metrics.vision_tokens_total,
        metrics.vision_usd_cost_total,
        metrics.circuit_state,
        metrics.transcripts_processed_total,
        metrics.manual_reviews_pending,
        metrics.webhook_deliveries_total,
        metrics.cache_hits_total,
        metrics.cache_misses_total,
    ):
        # prometheus_client appends _created/_sum/_count/_bucket; we
        # match the base "name" attribute (which is the prefix).
        out.add(collector._name)
    return out


def test_alerts_yaml_loads_with_groups() -> None:
    data = _load_alerts()
    assert "groups" in data
    groups = data["groups"]
    assert isinstance(groups, list) and groups, "groups must be a non-empty list"


def test_every_alert_has_required_fields() -> None:
    data = _load_alerts()
    for group in data["groups"]:
        assert "name" in group, "group missing 'name'"
        for rule in group.get("rules", []):
            assert "alert" in rule, f"rule missing 'alert' in group {group['name']}"
            assert "expr" in rule, f"alert {rule.get('alert')} missing 'expr'"
            severity = (rule.get("labels") or {}).get("severity")
            assert severity in {"page", "ticket"}, (
                f"alert {rule['alert']} has unknown severity {severity!r}"
            )
            summary = (rule.get("annotations") or {}).get("summary")
            assert summary, f"alert {rule['alert']} has no annotation summary"


_METRIC_NAME_RE = re.compile(r"\bocr2r_[a-z0-9_]+")


def test_alert_metric_references_match_declared_collectors() -> None:
    """Catch a metric typo in alert YAML before it ships."""
    data = _load_alerts()
    declared = _declared_metric_names()

    referenced: set[str] = set()
    for group in data["groups"]:
        for rule in group.get("rules", []):
            for match in _METRIC_NAME_RE.finditer(rule.get("expr", "")):
                referenced.add(match.group(0))

    # Histogram and counter suffixes (_bucket/_count/_sum/_total) attach
    # at scrape time, so strip them when comparing against declared base
    # names (prometheus_client also strips _total from Counter._name).
    canonical = {
        re.sub(r"_(bucket|count|sum|created|total)$", "", name) for name in referenced
    }
    unknown = canonical - declared
    assert not unknown, f"alert YAML references unknown metrics: {sorted(unknown)}"


def test_at_least_one_slo_alert_exists() -> None:
    """SLO group must exist with at least the three SLO alerts (per design plan)."""
    data = _load_alerts()
    slo_alerts: list[str] = []
    for group in data["groups"]:
        if group.get("name") == "ocr2r-slos":
            slo_alerts.extend(rule["alert"] for rule in group.get("rules", []))
    expected = {
        "Ocr2rAvailabilityBudgetBurn",
        "Ocr2rTranscriptsP95LatencyHigh",
        "Ocr2rConfidenceBudgetBurn",
    }
    missing = expected - set(slo_alerts)
    assert not missing, f"missing SLO alerts: {sorted(missing)}"


def test_grafana_dashboard_is_valid_json_with_panels() -> None:
    data = json.loads(DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert data.get("title")
    panels = data.get("panels")
    assert isinstance(panels, list) and panels, "dashboard must have panels"
    for panel in panels:
        assert "title" in panel
        assert panel.get("targets")


def test_grafana_dashboard_panels_reference_only_known_metrics() -> None:
    """Same drift-prevention trick as the alert test, applied to panels."""
    declared = _declared_metric_names()
    raw = DASHBOARD_PATH.read_text(encoding="utf-8")
    referenced = {
        re.sub(r"_(bucket|count|sum|created|total)$", "", m.group(0))
        for m in _METRIC_NAME_RE.finditer(raw)
    }
    unknown = referenced - declared
    assert not unknown, f"dashboard references unknown metrics: {sorted(unknown)}"


@pytest.mark.parametrize(
    "metric_substring",
    [
        "ocr2r_http_requests_total",
        "ocr2r_http_request_duration_seconds",
        "ocr2r_vision_confidence",
        "ocr2r_vision_usd_cost_total",
    ],
)
def test_dashboard_includes_core_metrics(metric_substring: str) -> None:
    raw = DASHBOARD_PATH.read_text(encoding="utf-8")
    assert metric_substring in raw, (
        f"core metric {metric_substring!r} missing from dashboard panels"
    )

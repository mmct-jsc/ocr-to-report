"""Phase 8 — SLA tier presets + loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from ocr_to_report.core.errors.domain import ValidationError
from ocr_to_report.core.sla import (
    SLA_PRESETS,
    SlaTier,
    TenantSlaConfig,
    load_preset,
    load_presets_from_dir,
)


def test_default_presets_cover_every_tier() -> None:
    """SLA_PRESETS must have an entry for every SlaTier value."""
    for tier in SlaTier:
        assert tier in SLA_PRESETS, f"missing in-code default for {tier!r}"


def test_economy_disallows_sync() -> None:
    economy = SLA_PRESETS[SlaTier.ECONOMY]
    assert economy.sync_allowed is False
    assert economy.provider_policy == "batch_only"


def test_premium_threshold_at_95() -> None:
    premium = SLA_PRESETS[SlaTier.PREMIUM]
    assert premium.confidence_threshold == 0.95
    assert premium.park_low_confidence is True
    assert premium.worm_audit is True


def test_enterprise_includes_siem() -> None:
    ent = SLA_PRESETS[SlaTier.ENTERPRISE]
    assert ent.siem_export is True
    assert ent.retention_days == 90


def test_load_preset_round_trip(tmp_path: Path) -> None:
    """Writing a YAML and loading it back yields the same Pydantic model."""
    yaml_text = """
tier: standard
sync_allowed: true
p95_target_seconds: 30.0
provider_policy: haiku_first
primary_model: claude-haiku-4-5
fallback_model: claude-sonnet-4-6
confidence_threshold: 0.85
park_low_confidence: true
retention_days: 30
audit_detail: standard
""".strip()
    path = tmp_path / "standard.yaml"
    path.write_text(yaml_text, encoding="utf-8")
    cfg = load_preset(SlaTier.STANDARD, root=tmp_path)
    assert isinstance(cfg, TenantSlaConfig)
    assert cfg.tier is SlaTier.STANDARD
    assert cfg.confidence_threshold == 0.85


def test_load_preset_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_preset(SlaTier.PREMIUM, root=tmp_path)


def test_load_presets_from_dir_loads_all_four(tmp_path: Path) -> None:
    """If all four YAMLs exist, every tier round-trips."""
    for tier in SlaTier:
        path = tmp_path / f"{tier.value}.yaml"
        # Round-trip the in-code defaults to YAML.
        cfg = SLA_PRESETS[tier]
        path.write_text(
            f"""
tier: {tier.value}
sync_allowed: {str(cfg.sync_allowed).lower()}
p95_target_seconds: {cfg.p95_target_seconds}
provider_policy: {cfg.provider_policy}
primary_model: {cfg.primary_model}
fallback_model: {cfg.fallback_model if cfg.fallback_model else "null"}
confidence_threshold: {cfg.confidence_threshold}
park_low_confidence: {str(cfg.park_low_confidence).lower()}
retention_days: {cfg.retention_days}
audit_detail: {cfg.audit_detail}
worm_audit: {str(cfg.worm_audit).lower()}
siem_export: {str(cfg.siem_export).lower()}
""".strip(),
            encoding="utf-8",
        )
    presets = load_presets_from_dir(tmp_path)
    assert set(presets.keys()) == set(SlaTier)
    assert presets[SlaTier.PREMIUM].confidence_threshold == 0.95


def test_load_preset_rejects_non_object_yaml(tmp_path: Path) -> None:
    path = tmp_path / "economy.yaml"
    path.write_text("just a string\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_preset(SlaTier.ECONOMY, root=tmp_path)


def test_tenant_sla_config_is_frozen() -> None:
    """TenantSlaConfig is immutable after construction."""
    cfg = SLA_PRESETS[SlaTier.STANDARD]
    with pytest.raises((AttributeError, TypeError, ValueError)):
        cfg.confidence_threshold = 0.5  # type: ignore[misc]

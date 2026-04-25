"""Phase 2 — loader error-path coverage."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ocr_to_report.core.errors.domain import (
    ProfileNotFoundError,
    TargetNotFoundError,
)
from ocr_to_report.core.profiles import (
    ProfileLoadError,
    ProfileRegistry,
    load_profile_bundle,
)
from ocr_to_report.core.targets import (
    TargetLoadError,
    TargetRegistry,
    load_target_bundle,
)

REPO_ROOT = Path(__file__).resolve().parents[3]


# ─── Helpers ──────────────────────────────────────────────────
def _polish_bundle_dir(tmp_path: Path) -> Path:
    """Copy the shipped Polish bundle into tmp_path so we can mutate it."""
    import shutil  # noqa: PLC0415

    src = REPO_ROOT / "profiles" / "pl.lo.swiadectwo_szkolne.v1"
    dst = tmp_path / "pl.lo.swiadectwo_szkolne.v1"
    shutil.copytree(src, dst)
    return dst


def _us_hs_bundle_dir(tmp_path: Path) -> Path:
    import shutil  # noqa: PLC0415

    src = REPO_ROOT / "targets" / "us-hs.v1"
    dst = tmp_path / "us-hs.v1"
    shutil.copytree(src, dst)
    return dst


# ─── Profile loader error paths ────────────────────────────────
def test_profile_loader_missing_required_file(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    (bundle / "vocabulary.yaml").unlink()
    with pytest.raises(ProfileLoadError, match="missing required file"):
        load_profile_bundle(bundle)


def test_profile_loader_yaml_parse_error(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    (bundle / "manifest.yaml").write_text(":\n  invalid: ::\n  yaml: ::\n", encoding="utf-8")
    with pytest.raises(ProfileLoadError):
        load_profile_bundle(bundle)


def test_profile_loader_validation_failure(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    bad = {"id": "pl.lo.swiadectwo_szkolne.v1", "name": "x"}  # missing required fields
    (bundle / "manifest.yaml").write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ProfileLoadError, match="validation"):
        load_profile_bundle(bundle)


def test_profile_loader_grade_scale_canonical_unknown(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    (bundle / "grade_scale.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "x.v1",
                "levels": [
                    {"raw_value": "a", "canonical": "MEH", "label": "a", "is_passing": True},
                    {"raw_value": "b", "canonical": "FAIL", "label": "b", "is_passing": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileLoadError, match="unknown canonical level"):
        load_profile_bundle(bundle)


def test_profile_loader_grade_scale_missing_normalized_or_canonical(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    (bundle / "grade_scale.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "x.v1",
                "levels": [
                    {"raw_value": "a", "label": "a", "is_passing": True},
                    {"raw_value": "b", "label": "b", "is_passing": False},
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileLoadError, match="must have either"):
        load_profile_bundle(bundle)


def test_profile_loader_grade_scale_canonical_inconsistent(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    (bundle / "grade_scale.yaml").write_text(
        yaml.safe_dump(
            {
                "id": "x.v1",
                "levels": [
                    # canonical FAIL but normalized lands in EXCELLENT band
                    {
                        "raw_value": "a",
                        "canonical": "FAIL",
                        "normalized": 0.9,
                        "label": "a",
                        "is_passing": False,
                    },
                    {
                        "raw_value": "b",
                        "canonical": "EXCELLENT",
                        "label": "b",
                        "is_passing": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ProfileLoadError, match="lands in"):
        load_profile_bundle(bundle)


# ─── Target loader error paths ─────────────────────────────────
def test_target_loader_missing_required_file(tmp_path: Path) -> None:
    bundle = _us_hs_bundle_dir(tmp_path)
    (bundle / "year_system.yaml").unlink()
    with pytest.raises(TargetLoadError, match="missing required file"):
        load_target_bundle(bundle)


def test_target_loader_invalid_canonical_level_in_grade_scale(tmp_path: Path) -> None:
    bundle = _us_hs_bundle_dir(tmp_path)
    raw = yaml.safe_load((bundle / "grade_scale.yaml").read_text(encoding="utf-8"))
    raw["levels"][0]["canonical_levels"] = ["MEH"]
    (bundle / "grade_scale.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(TargetLoadError, match="unknown canonical level"):
        load_target_bundle(bundle)


def test_target_loader_template_binding_missing_subject(tmp_path: Path) -> None:
    bundle = _us_hs_bundle_dir(tmp_path)
    (bundle / "templates" / "broken.binding.yaml").write_text(
        yaml.safe_dump(
            {
                "key": "broken",
                "blob_path": "broken.xlsx",
                "output_format": "xlsx",
                "target_year_index": 99,
                "bindings": [
                    {"cell": "A1", "kind": "subject.grade"}  # missing subject_id
                ],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(TargetLoadError, match="template binding validation"):
        load_target_bundle(bundle)


# ─── Profile registry error paths ──────────────────────────────
def test_profile_registry_invalid_root_raises(tmp_path: Path) -> None:
    with pytest.raises(ProfileLoadError, match="root directory not found"):
        ProfileRegistry(tmp_path / "nope")


def test_profile_registry_skips_dir_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "not-a-bundle").mkdir()
    (tmp_path / "with-manifest").mkdir()
    (tmp_path / "with-manifest" / "manifest.yaml").write_text("id: x", encoding="utf-8")
    pr = ProfileRegistry(tmp_path)
    assert pr.ids() == ["with-manifest"]


def test_profile_registry_directory_id_must_match_manifest(tmp_path: Path) -> None:
    bundle = _polish_bundle_dir(tmp_path)
    bundle.rename(bundle.parent / "wrong.directory.v1")
    pr = ProfileRegistry(tmp_path)
    with pytest.raises(ProfileLoadError, match="does not match manifest id"):
        pr.get("wrong.directory.v1")


def test_profile_registry_iter_all(tmp_path: Path) -> None:
    _polish_bundle_dir(tmp_path)
    pr = ProfileRegistry(tmp_path)
    bundles = list(pr.all())
    assert len(bundles) == 1
    assert bundles[0].id == "pl.lo.swiadectwo_szkolne.v1"


def test_profile_registry_unknown_id_raises(tmp_path: Path) -> None:
    pr = ProfileRegistry(tmp_path)
    with pytest.raises(ProfileNotFoundError):
        pr.get("any.id.v1")


# ─── Target registry error paths ───────────────────────────────
def test_target_registry_invalid_root_raises(tmp_path: Path) -> None:
    with pytest.raises(TargetLoadError, match="root directory not found"):
        TargetRegistry(tmp_path / "nope")


def test_target_registry_skips_dir_without_manifest(tmp_path: Path) -> None:
    (tmp_path / "not-a-bundle").mkdir()
    (tmp_path / "with-manifest").mkdir()
    (tmp_path / "with-manifest" / "manifest.yaml").write_text("id: x", encoding="utf-8")
    tr = TargetRegistry(tmp_path)
    assert tr.ids() == ["with-manifest"]


def test_target_registry_unknown_id_raises(tmp_path: Path) -> None:
    tr = TargetRegistry(tmp_path)
    with pytest.raises(TargetNotFoundError):
        tr.get("any.id.v1")


def test_target_registry_lazy_caches(tmp_path: Path) -> None:
    _us_hs_bundle_dir(tmp_path)
    tr = TargetRegistry(tmp_path)
    a = tr.get("us-hs.v1")
    b = tr.get("us-hs.v1")
    assert a is b


def test_target_registry_iter_all(tmp_path: Path) -> None:
    _us_hs_bundle_dir(tmp_path)
    tr = TargetRegistry(tmp_path)
    bundles = list(tr.all())
    assert len(bundles) == 1
    assert bundles[0].id == "us-hs.v1"


def test_target_registry_directory_id_must_match_manifest(tmp_path: Path) -> None:
    bundle = _us_hs_bundle_dir(tmp_path)
    bundle.rename(bundle.parent / "wrong.id.v1")
    tr = TargetRegistry(tmp_path)
    with pytest.raises(TargetLoadError, match="does not match manifest id"):
        tr.get("wrong.id.v1")

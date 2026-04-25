"""End-to-end pipeline + Excel renderer test.

Loads the real Polish profile and US-HS target bundles, runs the
``default_v1`` pipeline against a synthetic raw-extraction (the same
anonymized fixture the Phase 2 mapping test uses), and verifies the
produced xlsx contains the expected cell values at the expected
addresses.

Vision is mocked — this test does not call the real Anthropic API.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest
from openpyxl import load_workbook

from ocr_to_report.adapters.render import XlsxRenderer
from ocr_to_report.adapters.vision import (
    ExtractionResult,
    FixedPolicy,
    ProviderRouter,
    TokenUsage,
    VisionProvider,
    VisionRequest,
    compile_schema,
)
from ocr_to_report.core.pipeline import (
    PipelineContext,
    StepRegistry,
    StepStatus,
    load_pipeline,
    run_pipeline,
)
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.steps import register_default_steps
from ocr_to_report.core.targets import TargetRegistry

REPO_ROOT = Path(__file__).resolve().parents[3]


def _polish_grade9_raw_extraction() -> dict[str, Any]:
    """Same anonymized fixture as test_phase2_mapping.py."""
    return {
        "full_name": "Jan Kowalski",
        "birth_date": "2010-01-15",
        "school_year": "2023/2024",
        "current_class_name": "pierwszej",
        "school_name": "Test Academy LO",
        "city": "Warszawa",
        "region": "mazowieckie",
        "promoted": True,
        "promoted_with_distinction": True,
        "conduct": "wzorowe",
        "subjects": [
            {"raw_subject_name": "Język polski", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język angielski IV.1r.", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Język francuski IV.1p.", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Filozofia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Matematyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Fizyka", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Chemia", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Biologia", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Geografia", "raw_grade_value": "dobry"},
            {"raw_subject_name": "Informatyka", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Wychowanie fizyczne", "raw_grade_value": "bardzo dobry"},
            {"raw_subject_name": "Edukacja dla bezpieczeństwa", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Biznes i zarządzanie", "raw_grade_value": "celujący"},
            {"raw_subject_name": "Historia i teraźniejszość", "raw_grade_value": "celujący"},
        ],
        "advanced_subjects": ["Język angielski", "Geografia", "Matematyka", "Fizyka"],
    }


def _mock_vision_adapter(raw: dict[str, Any]) -> Any:
    """Return a minimal mock VisionAdapter that yields the given extraction."""

    class _MockAdapter:
        name = VisionProvider.MOCK

        def __init__(self) -> None:
            self.extract = AsyncMock(
                return_value=ExtractionResult(
                    raw_extraction=raw,
                    confidence=0.95,
                    field_confidences=None,
                    warnings=[],
                    provider=VisionProvider.MOCK,
                    model_id="mock",
                    usage=TokenUsage(input_tokens=1000, output_tokens=200, usd_cost=0.002),
                )
            )

        async def aclose(self) -> None:
            return None

    return _MockAdapter()


def _vision_request_factory(
    *,
    images: list[bytes],
    profile_bundle: Any,
    schema_dict: dict[str, Any],
) -> VisionRequest:
    """Build a VisionRequest from the pipeline's gathered context."""
    return VisionRequest(
        images=images,
        prompt=profile_bundle.extraction_prompt_template,
        output_schema=schema_dict,
        schema_version=profile_bundle.manifest.version,
        profile_id=profile_bundle.id,
    )


@pytest.mark.asyncio
async def test_default_v1_polish_to_us_hs_grade9_xlsx() -> None:
    profile_registry = ProfileRegistry(REPO_ROOT / "profiles")
    target_registry = TargetRegistry(REPO_ROOT / "targets")
    target_bundle_dir = REPO_ROOT / "targets" / "us-hs.v1"
    renderer = XlsxRenderer(target_bundle_dir)

    raw = _polish_grade9_raw_extraction()
    mock_adapter = _mock_vision_adapter(raw)
    router = ProviderRouter({VisionProvider.MOCK: mock_adapter}, FixedPolicy(VisionProvider.MOCK))

    step_registry = register_default_steps(StepRegistry())
    pipeline = load_pipeline(REPO_ROOT / "pipelines" / "default_v1.yaml", step_registry)

    ctx = PipelineContext(
        inputs={
            # raw_input_blob: a tiny placeholder PNG (preprocess accepts PNG bytes)
            "raw_input_blob": _png_bytes(),
            "profile_id": "pl.lo.swiadectwo_szkolne.v1",
            "target_id": "us-hs.v1",
        },
        services={
            "image_preprocessor": _identity_preprocessor,
            "profile_registry": profile_registry,
            "target_registry": target_registry,
            "vision_router": router,
            "schema_compiler": compile_schema,
            "vision_request_factory": _vision_request_factory,
            "renderer": renderer,
        },
    )

    run = await run_pipeline(pipeline, ctx)
    assert run.terminal_status is StepStatus.OK, run.error_detail

    # The output blob is a valid xlsx with key cells filled from render_data
    output = run.artifacts["output_blob"]
    assert isinstance(output, bytes)
    workbook = load_workbook(filename=io.BytesIO(output))
    sheet = workbook.active
    assert sheet is not None

    assert sheet["A2"].value == "Jan Kowalski"
    # Mathematics → A+ (celujący)
    assert sheet["D19"].value == "A+"
    # Mathematics advanced → 108 + 27 = 135h
    assert sheet["E19"].value == "135h"
    # English advanced → 81 + 27 = 108h
    assert sheet["D6"].value == "A"
    assert sheet["E6"].value == "108h"
    # Conduct passes through verbatim
    assert sheet["D3"].value == "wzorowe"


def _png_bytes() -> bytes:
    """Tiny 1x1 PNG, just enough for preprocess to accept (we mock around it)."""
    # We bypass actual preprocessing via _identity_preprocessor below.
    return b"\x89PNG\r\n\x1a\nplaceholder"


def _identity_preprocessor(blob: bytes) -> list[bytes]:
    """Pretend preprocessing succeeded — return blob as a single-page list."""
    return [blob]

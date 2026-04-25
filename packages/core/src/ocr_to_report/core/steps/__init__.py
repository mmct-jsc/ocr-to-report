"""Built-in pipeline steps.

Each step is a standalone class implementing :class:`Step`. The
:func:`register_default_steps` helper installs every built-in into a
:class:`StepRegistry` for use by :func:`load_pipeline`.
"""

from ocr_to_report.core.pipeline.registry import StepRegistry
from ocr_to_report.core.steps.detect_profile import (
    DetectProfileStep,
    detect_profile_step_factory,
)
from ocr_to_report.core.steps.extract import ExtractStep, extract_step_factory
from ocr_to_report.core.steps.human_review import (
    HumanReviewStep,
    human_review_step_factory,
)
from ocr_to_report.core.steps.map_to_target import (
    MapToTargetStep,
    map_to_target_step_factory,
)
from ocr_to_report.core.steps.notify_webhook import (
    NotifyWebhookStep,
    notify_webhook_step_factory,
)
from ocr_to_report.core.steps.persist import PersistStep, persist_step_factory
from ocr_to_report.core.steps.preprocess import (
    PreprocessStep,
    preprocess_step_factory,
)
from ocr_to_report.core.steps.quality_gate import (
    QualityGateStep,
    quality_gate_step_factory,
)
from ocr_to_report.core.steps.render import RenderStep, render_step_factory
from ocr_to_report.core.steps.translate import TranslateStep, translate_step_factory
from ocr_to_report.core.steps.validate import ValidateStep, validate_step_factory


def register_default_steps(registry: StepRegistry) -> StepRegistry:
    """Register every shipped step into ``registry`` and return it.

    Mutates the registry in place; returning it is a convenience for
    chaining/test setup.
    """
    registry.register("preprocess", preprocess_step_factory)
    registry.register("detect_profile", detect_profile_step_factory)
    registry.register("extract", extract_step_factory)
    registry.register("translate", translate_step_factory)
    registry.register("validate", validate_step_factory)
    registry.register("quality_gate", quality_gate_step_factory)
    registry.register("human_review", human_review_step_factory)
    registry.register("map", map_to_target_step_factory)
    registry.register("render", render_step_factory)
    registry.register("persist", persist_step_factory)
    registry.register("notify_webhook", notify_webhook_step_factory)
    return registry


__all__ = [
    "DetectProfileStep",
    "ExtractStep",
    "HumanReviewStep",
    "MapToTargetStep",
    "NotifyWebhookStep",
    "PersistStep",
    "PreprocessStep",
    "QualityGateStep",
    "RenderStep",
    "TranslateStep",
    "ValidateStep",
    "register_default_steps",
]

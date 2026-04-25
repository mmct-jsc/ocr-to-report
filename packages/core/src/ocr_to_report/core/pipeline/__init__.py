"""Pipeline engine: Step protocol, context, registry, engine, loader."""

from ocr_to_report.core.pipeline.engine import (
    Pipeline,
    PipelineError,
    PipelineRun,
    run_pipeline,
)
from ocr_to_report.core.pipeline.loader import PipelineLoadError, load_pipeline
from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    Step,
    StepMetrics,
    StepResult,
    StepStatus,
)
from ocr_to_report.core.pipeline.registry import (
    StepFactory,
    StepRegistry,
    StepRegistryError,
)

__all__ = [
    "Pipeline",
    "PipelineContext",
    "PipelineError",
    "PipelineLoadError",
    "PipelineRun",
    "Step",
    "StepFactory",
    "StepMetrics",
    "StepRegistry",
    "StepRegistryError",
    "StepResult",
    "StepStatus",
    "load_pipeline",
    "run_pipeline",
]

"""Pipeline engine — Step protocol, PipelineContext, StepResult.

Pipelines are ordered :class:`Step` instances. Each step adds typed
artifacts to the shared :class:`PipelineContext`; the next step reads
prior artifacts and adds its own. Steps **never mutate** prior artifacts
— this keeps pipelines fully traceable and replayable from any point.

The engine itself is in :mod:`engine`; this module contains only types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Mapping


class StepStatus(StrEnum):
    """Outcome of a single :meth:`Step.run` call.

    * ``ok`` — completed successfully; engine proceeds to the next step.
    * ``skip`` — step was a no-op (e.g., gate condition false); engine
      proceeds. Distinct from ``ok`` for telemetry.
    * ``fail`` — non-recoverable error; engine aborts and surfaces it.
    * ``park`` — step requires an out-of-band action (e.g., manual review
      approval); the engine returns control to the caller, who persists
      the partial state and resumes the pipeline later.
    """

    OK = "ok"
    SKIP = "skip"
    FAIL = "fail"
    PARK = "park"


@dataclass(frozen=True, slots=True)
class StepMetrics:
    """Per-step accounting attached to every :class:`StepResult`."""

    duration_ms: float = 0.0
    tokens_input: int = 0
    tokens_output: int = 0
    usd_cost: float = 0.0
    confidence: float | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    """The return value of :meth:`Step.run`.

    Attributes:
        status: Outcome — see :class:`StepStatus`.
        artifacts: Map of new artifact name → value to merge into the
            pipeline context. Steps MUST NOT include keys that already
            exist in ``ctx.artifacts`` (engine raises if they do).
        metrics: Operational telemetry.
        warnings: Non-fatal messages to surface to the caller.
        error_detail: Required iff ``status == FAIL``. Plain message for
            human consumption; engine wraps it into a domain error.
        park_reason: Required iff ``status == PARK``. Identifies what the
            caller must resolve before resuming (e.g., 'awaiting human
            review for low-confidence extraction').
    """

    status: StepStatus
    artifacts: dict[str, Any] = field(default_factory=dict)
    metrics: StepMetrics = field(default_factory=StepMetrics)
    warnings: list[str] = field(default_factory=list)
    error_detail: str | None = None
    park_reason: str | None = None


@dataclass(slots=True)
class PipelineContext:
    """Shared state across a pipeline run.

    Construct with the immutable inputs (PDF, profile id, target id,
    tenant SLA config, etc.) and any adapter handles the steps need.
    Steps add to ``artifacts`` via the engine — they do not mutate
    ``inputs`` or ``services``.

    Concrete adapter handles live in ``services`` as opaque objects;
    each step that needs a particular adapter declares it via a typed
    accessor (see step implementations).
    """

    inputs: Mapping[str, Any]
    """Original immutable inputs to the pipeline (raw bytes, IDs, config)."""

    services: Mapping[str, Any]
    """Adapter handles keyed by name (e.g., 'vision_router', 'blob_store').
    Steps look up what they need by key and assert the type."""

    artifacts: dict[str, Any] = field(default_factory=dict)
    """Outputs from prior steps. Engine merges StepResult.artifacts here
    after each successful step; steps read this read-only."""

    metrics: list[tuple[str, StepMetrics]] = field(default_factory=list)
    """Per-step metrics in execution order."""

    warnings: list[str] = field(default_factory=list)
    """Aggregated warnings from all steps so far."""

    def get(self, key: str, default: Any = None) -> Any:
        """Look up an artifact (or input as fallback)."""
        if key in self.artifacts:
            return self.artifacts[key]
        return self.inputs.get(key, default)

    def require(self, key: str) -> Any:
        """Look up a required artifact/input or raise."""
        value = self.get(key)
        if value is None:
            raise KeyError(
                f"pipeline context missing required key {key!r}; "
                f"available artifacts={sorted(self.artifacts)}, "
                f"inputs={sorted(self.inputs)}"
            )
        return value

    def service(self, name: str) -> Any:
        """Look up a required service handle."""
        try:
            return self.services[name]
        except KeyError as e:
            raise KeyError(
                f"pipeline context missing required service {name!r}; "
                f"available={sorted(self.services)}"
            ) from e


@runtime_checkable
class Step(Protocol):
    """Every pipeline step implements this single async method.

    Implementations must:

    * Be safe to share across concurrent pipeline runs (no instance state
      mutation).
    * Return ``StepStatus.OK`` when they did meaningful work and produced
      artifacts.
    * Translate adapter exceptions into ``StepStatus.FAIL`` results with
      a descriptive ``error_detail``; never let them propagate.
    """

    id: str
    """Stable id used to look up this step in the registry and pipeline YAML."""

    async def run(self, ctx: PipelineContext) -> StepResult:
        """Execute the step. See protocol contract above."""
        ...


__all__ = [
    "PipelineContext",
    "Step",
    "StepMetrics",
    "StepResult",
    "StepStatus",
]

"""Step registry — maps a step id (from YAML) to its constructor.

Steps that need configuration receive it as ``kwargs`` to their
constructor; the YAML's ``config:`` block is splatted into the call.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ocr_to_report.core.errors.domain import OcrToReportError
from ocr_to_report.core.pipeline.protocol import Step

StepFactory = Callable[..., Step]


class StepRegistryError(OcrToReportError):
    """A step id is unknown or its factory failed."""

    status = 500
    type_uri = "https://errors.ocr-to-report/step-registry"
    title = "Step registry error"


class StepRegistry:
    """Stable id → factory mapping.

    The registry is constructed empty and populated via :meth:`register`;
    pipelines look up steps by id at load time. Built-in steps register
    themselves through :func:`register_default_steps` (Phase 4); custom
    plugin steps are registered post-MVP via the same API.
    """

    def __init__(self) -> None:
        self._factories: dict[str, StepFactory] = {}

    def register(self, step_id: str, factory: StepFactory) -> None:
        if not step_id:
            raise StepRegistryError("step_id may not be empty")
        if step_id in self._factories:
            raise StepRegistryError(
                f"step {step_id!r} already registered",
                step_id=step_id,
            )
        self._factories[step_id] = factory

    def has(self, step_id: str) -> bool:
        return step_id in self._factories

    def ids(self) -> list[str]:
        return sorted(self._factories.keys())

    def build(self, step_id: str, config: dict[str, Any] | None = None) -> Step:
        try:
            factory = self._factories[step_id]
        except KeyError as e:
            raise StepRegistryError(
                f"unknown step id {step_id!r}; registered: {self.ids()}",
                step_id=step_id,
            ) from e
        try:
            step = factory(**(config or {}))
        except Exception as e:
            raise StepRegistryError(
                f"failed to construct step {step_id!r}: {e}",
                step_id=step_id,
            ) from e
        if step.id != step_id:
            raise StepRegistryError(
                f"factory for {step_id!r} produced step with id {step.id!r}",
                step_id=step_id,
                produced_id=step.id,
            )
        return step


__all__ = ["StepFactory", "StepRegistry", "StepRegistryError"]

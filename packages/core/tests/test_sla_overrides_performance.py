"""``resolve_with_overrides`` performance bar.

This function runs on every authenticated request that consults the
tenant's effective SLA (which is most of them). At 1,000 RPS we can't
afford milliseconds per call — the implementation does
``model_dump → apply_overrides → model_validate_json``, all
in-process, so the expected cost is microseconds.

This test enforces an honest ceiling so a future refactor (e.g.,
swapping Pydantic for a slower validator, or adding JSON-Schema
double-validation) doesn't silently regress performance.

We use ``time.process_time()`` (CPU time used by this process) rather
than ``time.perf_counter()`` so the test isn't sensitive to noisy
neighbours on shared CI runners. Each measurement is the *median* of
five 200-iteration runs to drop outliers without flagging a transient
GC pause as a regression.

Bars:
* 3-patch resolve: < 1ms per call median.
* 0-patch resolve: < 50us per call median (short-circuits, returns
  ``base`` directly).
"""

from __future__ import annotations

import statistics
import time

import pytest

from ocr_to_report.core.sla import SLA_PRESETS, SlaTier, resolve_with_overrides

ITERATIONS = 200
RUNS = 5
WARMUP = 100


def _median_per_call_ms(fn, iterations: int = ITERATIONS, runs: int = RUNS) -> float:
    """Median of ``runs`` runs of ``iterations`` calls, returned as
    milliseconds-per-call. Uses ``process_time`` so noisy neighbours
    on CI don't move the number."""
    for _ in range(WARMUP):
        fn()
    samples = []
    for _ in range(runs):
        start = time.process_time()
        for _ in range(iterations):
            fn()
        elapsed = time.process_time() - start
        samples.append(elapsed / iterations * 1000)  # ms per call
    return statistics.median(samples)


def test_resolve_with_overrides_is_under_1ms_median() -> None:
    """3 patches must run in median < 1ms per resolve. Measured locally
    at ~25us; the 1ms bar gives 40x CI headroom."""
    base = SLA_PRESETS[SlaTier.STANDARD]
    patches = [
        {"op": "set", "path": "confidence_threshold", "value": 0.95},
        {"op": "set", "path": "park_low_confidence", "value": False},
        {"op": "set", "path": "retention_days", "value": 60},
    ]

    def call() -> None:
        result = resolve_with_overrides(base, patches)
        # Sanity touch so JIT/cache effects can't hoist the call.
        assert result.confidence_threshold == 0.95

    median_ms = _median_per_call_ms(call)
    assert median_ms < 1.0, (
        f"resolve_with_overrides is too slow: {median_ms:.3f}ms median per call "
        f"(budget 1ms). Profile before relaxing the bar."
    )


def test_empty_patches_short_circuits_under_50us_median() -> None:
    """The no-patches path returns ``base`` directly — should be
    essentially free. Measured locally at ~0.5us; the 50us bar gives
    100x headroom (the empty path is the most common one in
    production)."""
    base = SLA_PRESETS[SlaTier.STANDARD]

    def call() -> None:
        result = resolve_with_overrides(base, [])
        assert result is base

    median_ms = _median_per_call_ms(call)
    assert median_ms < 0.05, (  # 50us = 0.05ms
        f"empty-patches short-circuit is too slow: {median_ms:.4f}ms median per "
        f"call (budget 0.05ms). The no-patches path should return ``base`` "
        f"directly without any work."
    )


@pytest.mark.skip(reason="Diagnostic only — uncomment to print numbers.")
def test_print_measured_numbers() -> None:
    """Diagnostic helper. Skipped by default."""
    base = SLA_PRESETS[SlaTier.STANDARD]
    patches = [
        {"op": "set", "path": "confidence_threshold", "value": 0.95},
        {"op": "set", "path": "park_low_confidence", "value": False},
        {"op": "set", "path": "retention_days", "value": 60},
    ]

    def with_patches() -> None:
        resolve_with_overrides(base, patches)

    def without_patches() -> None:
        resolve_with_overrides(base, [])

    print(
        f"\n3-patch median: {_median_per_call_ms(with_patches) * 1000:.1f}us "
        f"per call"
    )
    print(
        f"0-patch median: {_median_per_call_ms(without_patches) * 1000:.2f}us "
        f"per call"
    )

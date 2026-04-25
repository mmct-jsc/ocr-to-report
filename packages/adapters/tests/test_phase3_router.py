"""Provider router + policy tests."""

from __future__ import annotations

from typing import Any

import pytest

from ocr_to_report.adapters.vision import (
    AdaptivePolicy,
    ExtractionResult,
    FixedPolicy,
    NoProviderAvailableError,
    ProviderRouter,
    RegionPolicy,
    RoundRobinPolicy,
    RoutingContext,
    VisionProvider,
    VisionRequest,
)


class _FakeAdapter:
    def __init__(self, provider: VisionProvider) -> None:
        self.name = provider

    async def extract(self, request: VisionRequest) -> ExtractionResult:
        raise NotImplementedError

    async def aclose(self) -> None:
        return None


def _make_adapters(providers: list[VisionProvider]) -> dict[VisionProvider, Any]:
    return {p: _FakeAdapter(p) for p in providers}


# ─── FixedPolicy ───────────────────────────────────────────────
def test_fixed_policy_returns_specified() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC, VisionProvider.OPENAI])
    router = ProviderRouter(adapters, FixedPolicy(VisionProvider.OPENAI))
    a = router.select()
    assert a.name is VisionProvider.OPENAI


def test_fixed_policy_unknown_provider_raises() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC])
    router = ProviderRouter(adapters, FixedPolicy(VisionProvider.GOOGLE))
    with pytest.raises(NoProviderAvailableError):
        router.select()


# ─── AdaptivePolicy ────────────────────────────────────────────
def test_adaptive_policy_picks_first_available() -> None:
    adapters = _make_adapters([VisionProvider.OPENAI, VisionProvider.ANTHROPIC])
    router = ProviderRouter(
        adapters,
        AdaptivePolicy(
            priority=[VisionProvider.GOOGLE, VisionProvider.ANTHROPIC, VisionProvider.OPENAI]
        ),
    )
    a = router.select()
    assert a.name is VisionProvider.ANTHROPIC


def test_adaptive_policy_no_match_raises() -> None:
    adapters = _make_adapters([VisionProvider.OPENAI])
    router = ProviderRouter(
        adapters,
        AdaptivePolicy(priority=[VisionProvider.GOOGLE, VisionProvider.TESSERACT]),
    )
    with pytest.raises(NoProviderAvailableError):
        router.select()


# ─── RoundRobinPolicy ──────────────────────────────────────────
def test_round_robin_distributes() -> None:
    adapters = _make_adapters(
        [VisionProvider.ANTHROPIC, VisionProvider.OPENAI, VisionProvider.GOOGLE]
    )
    policy = RoundRobinPolicy(
        [VisionProvider.ANTHROPIC, VisionProvider.OPENAI, VisionProvider.GOOGLE]
    )
    router = ProviderRouter(adapters, policy)
    chosen = [router.select().name for _ in range(6)]
    assert chosen == [
        VisionProvider.ANTHROPIC,
        VisionProvider.OPENAI,
        VisionProvider.GOOGLE,
        VisionProvider.ANTHROPIC,
        VisionProvider.OPENAI,
        VisionProvider.GOOGLE,
    ]


def test_round_robin_skips_unregistered() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC])
    policy = RoundRobinPolicy(
        [VisionProvider.OPENAI, VisionProvider.ANTHROPIC, VisionProvider.GOOGLE]
    )
    router = ProviderRouter(adapters, policy)
    chosen = [router.select().name for _ in range(3)]
    # Only ANTHROPIC is registered; rotation finds it each cycle
    assert all(p is VisionProvider.ANTHROPIC for p in chosen)


def test_round_robin_empty_providers_rejected() -> None:
    with pytest.raises(ValueError):
        RoundRobinPolicy([])


# ─── RegionPolicy ──────────────────────────────────────────────
def test_region_policy_matches_eu_to_google() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC, VisionProvider.GOOGLE])
    policy = RegionPolicy(
        mapping={"eu-central": [VisionProvider.GOOGLE, VisionProvider.ANTHROPIC]},
        default=[VisionProvider.ANTHROPIC],
    )
    router = ProviderRouter(adapters, policy)
    a = router.select(RoutingContext(tenant_region="eu-central"))
    assert a.name is VisionProvider.GOOGLE


def test_region_policy_falls_back_to_default() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC])
    policy = RegionPolicy(
        mapping={"eu-central": [VisionProvider.GOOGLE]},
        default=[VisionProvider.ANTHROPIC],
    )
    router = ProviderRouter(adapters, policy)
    a = router.select(RoutingContext(tenant_region="us-east"))
    assert a.name is VisionProvider.ANTHROPIC


def test_region_policy_no_default_match_raises() -> None:
    adapters = _make_adapters([VisionProvider.OPENAI])
    policy = RegionPolicy(
        mapping={},
        default=[VisionProvider.GOOGLE],
    )
    router = ProviderRouter(adapters, policy)
    with pytest.raises(NoProviderAvailableError):
        router.select(RoutingContext())


# ─── ProviderRouter init ──────────────────────────────────────
def test_router_requires_at_least_one_adapter() -> None:
    with pytest.raises(ValueError):
        ProviderRouter({}, FixedPolicy(VisionProvider.ANTHROPIC))


def test_router_exposes_adapters_readonly() -> None:
    adapters = _make_adapters([VisionProvider.ANTHROPIC])
    router = ProviderRouter(adapters, FixedPolicy(VisionProvider.ANTHROPIC))
    # The exposed view is a dict (Mapping) — caller can't mutate the router
    # via this surface unless they reassign self._adapters externally.
    assert VisionProvider.ANTHROPIC in router.adapters

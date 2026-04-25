"""Provider router — selects a :class:`VisionAdapter` per request.

Policies:

* :class:`FixedPolicy` — always use the same provider (the simplest case;
  used by the default Standard SLA tier).
* :class:`AdaptivePolicy` — try providers in priority order, falling
  through on transient errors. Confidence-gated fallback is handled
  *inside* the Anthropic adapter; this layer handles outage failover.
* :class:`RoundRobinPolicy` — distribute across available providers in
  rotation. Useful when one provider is rate-limited.
* :class:`RegionPolicy` — pick a provider whose declared region matches
  the request's tenant region (e.g., EU tenant → Google Vertex EU).

All policies are pure: no I/O, no globals.

Selecting a provider does NOT call it. The router returns a
:class:`VisionAdapter` instance; the caller invokes ``extract()``.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ocr_to_report.adapters.vision.protocol import VisionAdapter, VisionProvider
from ocr_to_report.core.errors.domain import OcrToReportError


class NoProviderAvailableError(OcrToReportError):
    """No provider matched the routing policy + request."""

    status = 503
    type_uri = "https://errors.ocr-to-report/no-vision-provider"
    title = "No vision provider available"


@dataclass(frozen=True, slots=True)
class RoutingContext:
    """Per-request context the router uses to choose a provider.

    Kept minimal so policies remain testable in isolation.
    """

    tenant_region: str | None = None
    """Tenant's pinned region (e.g., 'us-east', 'eu-central'); used by RegionPolicy."""


@runtime_checkable
class RoutingPolicy(Protocol):
    """All policies implement this single method."""

    def select(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        ctx: RoutingContext,
    ) -> VisionAdapter:
        """Return the chosen adapter, or raise :class:`NoProviderAvailableError`."""
        ...


@dataclass(slots=True)
class FixedPolicy:
    """Always pick a single named provider."""

    provider: VisionProvider

    def select(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        ctx: RoutingContext,
    ) -> VisionAdapter:
        adapter = adapters.get(self.provider)
        if adapter is None:
            raise NoProviderAvailableError(
                f"FixedPolicy requires provider {self.provider.value} but it is not registered",
                requested=self.provider.value,
                registered=[p.value for p in adapters],
            )
        return adapter


@dataclass(slots=True)
class AdaptivePolicy:
    """Pick the first registered provider in the configured priority order.

    This is **outage failover** at the routing layer; quality fallback
    (low-confidence retry against a stronger model) lives inside the
    Anthropic adapter itself.
    """

    priority: list[VisionProvider]

    def select(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        ctx: RoutingContext,
    ) -> VisionAdapter:
        for provider in self.priority:
            if provider in adapters:
                return adapters[provider]
        raise NoProviderAvailableError(
            "AdaptivePolicy: none of the priority providers are registered",
            priority=[p.value for p in self.priority],
            registered=[p.value for p in adapters],
        )


class RoundRobinPolicy:
    """Cycle through providers in registration order.

    Stateful: the underlying iterator is mutated on each call. The router
    instance must be shared across requests for round-robin to actually
    distribute load.
    """

    def __init__(self, providers: list[VisionProvider]) -> None:
        if not providers:
            raise ValueError("RoundRobinPolicy requires at least one provider")
        self._providers = list(providers)
        self._cycle = itertools.cycle(self._providers)

    def select(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        ctx: RoutingContext,
    ) -> VisionAdapter:
        # Try at most len(providers) times so a fully-empty registry fails fast
        for _ in range(len(self._providers)):
            candidate = next(self._cycle)
            if candidate in adapters:
                return adapters[candidate]
        raise NoProviderAvailableError(
            "RoundRobinPolicy: none of the rotation providers are registered",
            providers=[p.value for p in self._providers],
            registered=[p.value for p in adapters],
        )


@dataclass(slots=True)
class RegionPolicy:
    """Region-aware provider selection.

    ``mapping`` is region → ordered priority list of providers. The
    request's ``ctx.tenant_region`` selects the priority list. Within a
    region the policy behaves like :class:`AdaptivePolicy`.

    Falls back to ``default`` if the tenant region is not in the mapping
    (or is None).
    """

    mapping: dict[str, list[VisionProvider]]
    default: list[VisionProvider]

    def select(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        ctx: RoutingContext,
    ) -> VisionAdapter:
        priority = self.mapping.get(ctx.tenant_region or "", self.default)
        for provider in priority:
            if provider in adapters:
                return adapters[provider]
        raise NoProviderAvailableError(
            f"RegionPolicy: no priority provider for region {ctx.tenant_region!r} is registered",
            region=ctx.tenant_region,
            priority=[p.value for p in priority],
            registered=[p.value for p in adapters],
        )


# ─── Router ────────────────────────────────────────────────────
class ProviderRouter:
    """Pairs a registry of adapters with a routing policy."""

    def __init__(
        self,
        adapters: Mapping[VisionProvider, VisionAdapter],
        policy: RoutingPolicy,
    ) -> None:
        if not adapters:
            raise ValueError("ProviderRouter requires at least one adapter")
        self._adapters = dict(adapters)
        self._policy = policy

    @property
    def adapters(self) -> Mapping[VisionProvider, VisionAdapter]:
        return self._adapters

    def select(self, ctx: RoutingContext | None = None) -> VisionAdapter:
        return self._policy.select(self._adapters, ctx or RoutingContext())


__all__ = [
    "AdaptivePolicy",
    "FixedPolicy",
    "NoProviderAvailableError",
    "ProviderRouter",
    "RegionPolicy",
    "RoundRobinPolicy",
    "RoutingContext",
    "RoutingPolicy",
]

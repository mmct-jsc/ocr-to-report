"""Worker process context — long-lived services injected into handlers.

Mirrors the API's :class:`AppState` but for out-of-process work. Built
once per process (in :func:`build_worker_context`) and passed by
reference to every handler invocation.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ocr_to_report.adapters.blob import BlobStore, LocalBlobStore, S3BlobStore
from ocr_to_report.adapters.crypto import EnvelopeEncryptor, EnvKEKProvider
from ocr_to_report.adapters.queue import InMemoryQueue, Queue
from ocr_to_report.adapters.vision import (
    AdaptivePolicy,
    AnthropicBatchAdapter,
    AnthropicVisionAdapter,
    InMemoryAsyncCache,
    ProviderRouter,
    VisionProvider,
)
from ocr_to_report.core.profiles import ProfileRegistry
from ocr_to_report.core.targets import TargetRegistry

if TYPE_CHECKING:
    from ocr_to_report.api.settings import Settings


@dataclass(slots=True)
class WorkerContext:
    """Long-lived services every worker handler needs.

    Constructed once per worker process. Each handler receives this and
    a per-task envelope; handlers MUST NOT mutate the context.
    """

    settings: Settings
    queue: Queue
    encryptor: EnvelopeEncryptor
    profile_registry: ProfileRegistry
    target_registry: TargetRegistry
    blob_store: BlobStore
    vision_router: ProviderRouter
    batch_adapter: AnthropicBatchAdapter | None
    """``None`` when ``ANTHROPIC_API_KEY`` is unset (tests/local dev)."""
    result_cache: InMemoryAsyncCache
    bundle_roots: dict[str, Path]


def build_worker_context(
    settings: Settings,
    *,
    queue: Queue | None = None,
) -> WorkerContext:
    """Assemble a :class:`WorkerContext` from app settings.

    The queue argument lets tests inject an in-memory queue. Production
    deployments leave it ``None`` and the function picks a queue
    backend based on settings (Redis when configured, in-memory
    otherwise — the in-memory choice is only safe in single-process
    deployments).
    """
    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))

    profile_registry = ProfileRegistry(settings.profiles_root.resolve())
    target_registry = TargetRegistry(settings.targets_root.resolve())

    blob_store: BlobStore
    if settings.blob_backend == "local":
        blob_store = LocalBlobStore(settings.blob_local_root.resolve())
    else:
        blob_store = S3BlobStore(
            bucket=settings.blob_bucket,
            endpoint_url=settings.blob_endpoint_url,
            region=settings.blob_region,
            access_key=settings.blob_access_key,
            secret_key=settings.blob_secret_key,
        )

    vision_router, batch_adapter = _build_vision_stack(settings)

    bundle_roots = {
        target.id: (settings.targets_root / target.id).resolve() for target in target_registry.all()
    }

    return WorkerContext(
        settings=settings,
        queue=queue or InMemoryQueue(),
        encryptor=encryptor,
        profile_registry=profile_registry,
        target_registry=target_registry,
        blob_store=blob_store,
        vision_router=vision_router,
        batch_adapter=batch_adapter,
        result_cache=InMemoryAsyncCache(),
        bundle_roots=bundle_roots,
    )


def _build_vision_stack(
    settings: Settings,
) -> tuple[ProviderRouter, AnthropicBatchAdapter | None]:
    """Build the sync router + the (optional) batch adapter.

    Returns a tuple so the worker can route batch submissions directly to
    the batch adapter without having to re-introspect the router.
    """
    adapters: dict[VisionProvider, Any] = {}
    batch: AnthropicBatchAdapter | None = None

    if settings.anthropic_api_key:
        from anthropic import AsyncAnthropic  # noqa: PLC0415

        client = AsyncAnthropic(api_key=settings.anthropic_api_key)
        adapters[VisionProvider.ANTHROPIC] = AnthropicVisionAdapter(
            client,
            primary_model="claude-haiku-4-5",
            fallback_model="claude-sonnet-4-6",
        )
        batch = AnthropicBatchAdapter(client, model="claude-haiku-4-5")

    if not adapters:
        from ocr_to_report.adapters.vision.stub_adapters import (  # noqa: PLC0415
            OpenAIVisionAdapter,
        )

        adapters[VisionProvider.OPENAI] = OpenAIVisionAdapter()

    priority = [
        VisionProvider.ANTHROPIC,
        VisionProvider.OPENAI,
        VisionProvider.GOOGLE,
        VisionProvider.TESSERACT,
    ]
    router = ProviderRouter(adapters, AdaptivePolicy(priority=priority))
    return router, batch


__all__ = ["WorkerContext", "build_worker_context"]

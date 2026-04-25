"""Vision adapter layer.

Public surface:

* :class:`VisionAdapter` — protocol every provider implements.
* :class:`VisionRequest` / :class:`ExtractionResult` / :class:`TokenUsage` — types.
* :class:`AnthropicVisionAdapter` — primary provider, fully implemented.
* :class:`OpenAIVisionAdapter`, :class:`GoogleVisionAdapter`,
  :class:`TesseractAdapter` — interface stubs (raise NotImplementedError).
* :class:`ProviderRouter` + policies — selects the adapter per request.
* :func:`preprocess` — image preprocessing pipeline.
* :class:`InMemoryAsyncCache` + helpers — result cache.
* :func:`compile_schema` — translates a profile extraction schema to JSON
  Schema for the adapter.
"""

from ocr_to_report.adapters.vision.anthropic_adapter import AnthropicVisionAdapter
from ocr_to_report.adapters.vision.preprocessing import (
    PreprocessConfig,
    detect_media_type,
    preprocess,
)
from ocr_to_report.adapters.vision.protocol import (
    ExtractionResult,
    TokenUsage,
    VisionAdapter,
    VisionProvider,
    VisionRequest,
)
from ocr_to_report.adapters.vision.result_cache import (
    AsyncCache,
    InMemoryAsyncCache,
    deserialize_result,
    make_cache_key,
    serialize_result,
)
from ocr_to_report.adapters.vision.router import (
    AdaptivePolicy,
    FixedPolicy,
    NoProviderAvailableError,
    ProviderRouter,
    RegionPolicy,
    RoundRobinPolicy,
    RoutingContext,
    RoutingPolicy,
)
from ocr_to_report.adapters.vision.schema_compiler import compile_schema
from ocr_to_report.adapters.vision.stub_adapters import (
    GoogleVisionAdapter,
    OpenAIVisionAdapter,
    TesseractAdapter,
)

__all__ = [
    "AdaptivePolicy",
    "AnthropicVisionAdapter",
    "AsyncCache",
    "ExtractionResult",
    "FixedPolicy",
    "GoogleVisionAdapter",
    "InMemoryAsyncCache",
    "NoProviderAvailableError",
    "OpenAIVisionAdapter",
    "PreprocessConfig",
    "ProviderRouter",
    "RegionPolicy",
    "RoundRobinPolicy",
    "RoutingContext",
    "RoutingPolicy",
    "TesseractAdapter",
    "TokenUsage",
    "VisionAdapter",
    "VisionProvider",
    "VisionRequest",
    "compile_schema",
    "deserialize_result",
    "detect_media_type",
    "make_cache_key",
    "preprocess",
    "serialize_result",
]

"""Extract step — call the vision provider through the router.

Reads preprocessed images and the profile bundle, compiles the schema,
calls the routed vision adapter, and produces ``extraction_result``.

The result cache is consulted on the way in (if a cache service is
present) and updated on the way out. The router selects the provider
per the tenant's SLA-driven policy.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ocr_to_report.core.pipeline.protocol import (
    PipelineContext,
    StepMetrics,
    StepResult,
    StepStatus,
)


@dataclass(slots=True)
class ExtractStepConfig:
    """Per-pipeline configuration for the extract step.

    These are the knobs the YAML's ``config:`` block sets. Anything
    SLA-tier dependent (provider mix, confidence threshold) is plumbed
    through the tenant config rather than here so the same YAML can
    serve multiple tiers.
    """

    profile_extraction_field: str = "raw_extraction"
    """Artifact key under which the raw_extraction dict is stored."""


class ExtractStep:
    """Vision extraction step.

    Services required:
        - ``vision_router`` — :class:`ProviderRouter`
        - ``schema_compiler`` — callable
          ``(ProfileExtractionSchema) -> dict[str, Any]`` (JSON Schema)
        - ``result_cache`` (optional) — :class:`AsyncCache`
        - ``cache_key_fn`` (optional, paired with ``result_cache``) —
          callable ``(images, provider, schema_version) -> str``
        - ``cache_serialize_fn`` / ``cache_deserialize_fn`` (optional)

    Reads:
        - ``preprocessed_images`` (list[bytes])
        - ``profile_bundle`` (:class:`ProfileBundle`)
        - ``routing_context`` (optional, :class:`RoutingContext`)

    Produces:
        - ``extraction_result`` (:class:`ExtractionResult`)
        - ``raw_extraction`` (dict[str, Any])
    """

    id: str = "extract"

    def __init__(
        self,
        *,
        profile_extraction_field: str = "raw_extraction",
        # provider_policy / confidence_threshold are documented for YAML
        # authoring but routed via tenant SLA at runtime; accept and ignore
        # them here so YAMLs in the wild don't break.
        provider_policy: str | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self._cfg = ExtractStepConfig(
            profile_extraction_field=profile_extraction_field,
        )
        # Acknowledge but don't enforce these — the router & adapter own them.
        self._provider_policy_hint = provider_policy
        self._confidence_threshold_hint = confidence_threshold

    async def run(self, ctx: PipelineContext) -> StepResult:
        start = time.monotonic()
        try:
            router = ctx.service("vision_router")
            schema_compiler = ctx.service("schema_compiler")
            request_factory = ctx.service("vision_request_factory")
            images = ctx.require("preprocessed_images")
            profile_bundle = ctx.require("profile_bundle")
            routing_context = ctx.get("routing_context")

            schema_dict = schema_compiler(profile_bundle.extraction_schema)
            adapter = router.select(routing_context)

            request = request_factory(
                images=images,
                profile_bundle=profile_bundle,
                schema_dict=schema_dict,
            )

            cache = ctx.services.get("result_cache")
            cache_key_fn = ctx.services.get("cache_key_fn")
            deserialize = ctx.services.get("cache_deserialize_fn")
            serialize = ctx.services.get("cache_serialize_fn")
            cache_ttl = int(ctx.services.get("cache_ttl_seconds", 3600))

            cache_key: str | None = None
            if cache is not None and cache_key_fn is not None and deserialize is not None:
                cache_key = cache_key_fn(images, adapter.name, request.schema_version)
                cached_blob = await cache.get(cache_key)
                if cached_blob is not None:
                    result = deserialize(cached_blob)
                    duration = (time.monotonic() - start) * 1000
                    return StepResult(
                        status=StepStatus.OK,
                        artifacts={
                            "extraction_result": result,
                            self._cfg.profile_extraction_field: result.raw_extraction,
                        },
                        metrics=StepMetrics(
                            duration_ms=duration,
                            confidence=result.confidence,
                        ),
                        warnings=["cache hit — skipping vision call"],
                    )

            result = await adapter.extract(request)

            if cache is not None and cache_key is not None and serialize is not None:
                await cache.set(cache_key, serialize(result), ttl_seconds=cache_ttl)
        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            return StepResult(
                status=StepStatus.FAIL,
                metrics=StepMetrics(duration_ms=duration),
                error_detail=f"extract failed: {type(e).__name__}: {e}",
            )

        duration = (time.monotonic() - start) * 1000
        return StepResult(
            status=StepStatus.OK,
            artifacts={
                "extraction_result": result,
                self._cfg.profile_extraction_field: result.raw_extraction,
            },
            metrics=StepMetrics(
                duration_ms=duration,
                tokens_input=result.usage.input_tokens,
                tokens_output=result.usage.output_tokens,
                usd_cost=result.usage.usd_cost,
                confidence=result.confidence,
            ),
            warnings=list(result.warnings),
        )


def extract_step_factory(**kwargs: object) -> ExtractStep:
    return ExtractStep(**kwargs)  # type: ignore[arg-type]


__all__ = ["ExtractStep", "extract_step_factory"]

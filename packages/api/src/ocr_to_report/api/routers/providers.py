"""``/v1/tenant/providers`` — per-tenant BYOK CRUD (v0.3.0).

Three endpoints, one provider live (``anthropic``):

* ``GET    /v1/tenant/providers`` — list, redacted. Returns one row per
  provider that has ever had a credential (active or inactive). The
  ``api_key_redacted`` field is ``sk-ant-…XXXX``; the plaintext is
  never echoed back, not even to the same tenant that set it.

* ``PUT    /v1/tenant/providers/{provider}`` — upsert. Validates the
  candidate API key against the provider's listing endpoint (Anthropic
  ``/v1/models``) so a bad key returns 400 BEFORE anything is
  persisted. Results are cached in-process for 60s so repeated PUTs of
  the same key don't hammer the provider. Audits
  ``provider.byok_created`` or ``provider.byok_rotated``.

* ``DELETE /v1/tenant/providers/{provider}`` — soft-disable the active
  row (``active=False, rotated_at=now()``). Returns 204 even when no
  active row exists (idempotent). Audits ``provider.byok_revoked``
  when a row was actually disabled.

v0.3.0 scope: only ``provider="anthropic"`` is validated and routable.
The other three legal provider ids (``openai``, ``google_vertex``,
``tesseract``) return 501 from PUT with a "shipped in v0.7.0" hint.
Unknown provider ids return 422.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Annotated, Final, get_args

from fastapi import APIRouter, Depends, Response

from ocr_to_report.adapters.db.repositories import TenantProviderCredentialRepo
from ocr_to_report.api.deps import RequestRepos, get_repos
from ocr_to_report.api.schemas import (
    ProviderId,
    ProvidersListResponse,
    ProviderStatus,
    ProviderUpsertRequest,
)
from ocr_to_report.core.errors.domain import OcrToReportError, ValidationError

router = APIRouter(prefix="/v1", tags=["tenant_providers"])


# ─── 501 for not-yet-shipped providers ────────────────────────────────


class _ProviderNotShippedError(OcrToReportError):
    """v0.3.0 only routes anthropic; the others are accepted-but-501."""

    status = 501
    type_uri = "https://errors.ocr-to-report/provider-not-shipped"
    title = "Provider not yet supported"


_VALIDATED_PROVIDERS: Final[frozenset[str]] = frozenset({"anthropic"})
"""Providers whose PUT path actually validates + persists. Adding to
this set in v0.7.0 unblocks the others; no schema change needed."""


# ─── In-process key-validation cache ──────────────────────────────────


_VALIDATION_TTL_SECONDS: Final[int] = 60
"""Per the BYOK plan's "cache 60s" risk-mitigation note: a Settings UI
that PUTs twice in quick succession shouldn't hammer Anthropic. Cache
the result of the validation call. Keyed by ``(provider, api_key)``."""

_validation_cache: dict[tuple[str, str], tuple[bool, float]] = {}
_validation_lock = asyncio.Lock()


def _cache_get(provider: str, api_key: str) -> bool | None:
    key = (provider, api_key)
    cached = _validation_cache.get(key)
    if cached is None:
        return None
    is_valid, written_at = cached
    if (time.time() - written_at) > _VALIDATION_TTL_SECONDS:
        _validation_cache.pop(key, None)
        return None
    return is_valid


def _cache_put(provider: str, api_key: str, is_valid: bool) -> None:
    _validation_cache[(provider, api_key)] = (is_valid, time.time())


async def _validate_anthropic_key(api_key: str) -> bool:
    """Probe ``/v1/models`` with the candidate key.

    Returns True on 2xx, False on 401/403. Other failures (network,
    timeout) raise :class:`ValidationError` so the PUT returns 400 with
    a clear "couldn't validate" message rather than silently accepting
    a key whose validity is unknown.
    """
    cached = _cache_get("anthropic", api_key)
    if cached is not None:
        return cached

    async with _validation_lock:
        # Re-check under the lock — another request might have populated
        # the cache while we were waiting.
        cached = _cache_get("anthropic", api_key)
        if cached is not None:
            return cached

        import anthropic  # noqa: PLC0415

        client = anthropic.AsyncAnthropic(api_key=api_key)
        try:
            await client.models.list(limit=1)
            _cache_put("anthropic", api_key, True)
            return True
        except anthropic.AuthenticationError:
            _cache_put("anthropic", api_key, False)
            return False
        except anthropic.PermissionDeniedError:
            _cache_put("anthropic", api_key, False)
            return False
        except Exception as e:
            # Network / timeout / transient: don't cache, propagate as
            # 400 so the tenant retries rather than thinking their key
            # was silently accepted.
            raise ValidationError(
                f"could not validate Anthropic key (transient): {type(e).__name__}",
            ) from e
        finally:
            aclose = getattr(client, "aclose", None)
            if aclose is not None:
                # Best-effort cleanup — never let a close failure mask
                # the validation result we just computed.
                with contextlib.suppress(Exception):
                    await aclose()


# ─── helpers ─────────────────────────────────────────────────────────


def _redact_key(api_key: str) -> str:
    """Return the last four characters with a fixed prefix marker.

    Format: ``sk-ant-…XXXX`` regardless of the actual prefix — the goal
    is "we recognise this key" not "we echo back its bytes". Real keys
    short enough to be shorter than the displayed tail collapse to
    ``sk-ant-…<entire-key>`` which is acceptable (the unit-test schema
    requires ``min_length=8``, so the tail is always at least 4 chars).
    """
    tail = api_key[-4:] if len(api_key) >= 4 else api_key
    return f"sk-ant-…{tail}"


def _summarize(row: object) -> ProviderStatus:
    """Build a :class:`ProviderStatus` from a credential row.

    We do NOT unwrap the key here — the redacted view derives from the
    last-4-of-plaintext convention, so we'd need the plaintext. Instead
    the writer at PUT time stores the redacted form on the audit; the
    GET surface returns a placeholder ``sk-ant-…••••`` rather than
    re-decrypting on every read.
    """
    return ProviderStatus(
        provider=row.provider,  # type: ignore[attr-defined]
        active=row.active,  # type: ignore[attr-defined]
        api_key_redacted=_PLACEHOLDER_REDACTED,
        region=row.region,  # type: ignore[attr-defined]
        rotated_at=row.rotated_at,  # type: ignore[attr-defined]
        created_at=row.created_at,  # type: ignore[attr-defined]
        updated_at=row.updated_at,  # type: ignore[attr-defined]
    )


_PLACEHOLDER_REDACTED: Final[str] = "sk-ant-…••••"
"""Fixed placeholder used by GET. Avoids per-read decryption (which would
need the tenant DEK on the read path just to compute a UI affordance).
The PUT-time audit trail carries the last-4 redaction for the tenant
that wants to confirm which key they uploaded."""


def _require_known_provider(provider: str) -> None:
    """Raise 422 if ``provider`` is not in the schema's literal set."""
    legal = set(get_args(ProviderId))
    if provider not in legal:
        raise ValidationError(
            f"unknown provider {provider!r}; legal values: {sorted(legal)}",
            provider=provider,
        )


# ─── GET /v1/tenant/providers ────────────────────────────────────────


@router.get(
    "/tenant/providers",
    response_model=ProvidersListResponse,
    responses={401: {"description": "Authentication required"}},
)
async def list_providers(
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> ProvidersListResponse:
    """List credentials. Keys are redacted to ``sk-ant-…••••``.

    Returns every row the tenant has ever uploaded, active OR inactive,
    so the UI can label disabled rows clearly. Sorted newest-first by
    ``created_at`` (the repo's natural order)."""
    creds = TenantProviderCredentialRepo(repos.session, repos.encryptor)
    rows = await creds.list_for_tenant(repos.tenant.id)
    return ProvidersListResponse(providers=[_summarize(r) for r in rows])


# ─── PUT /v1/tenant/providers/{provider} ─────────────────────────────


@router.put(
    "/tenant/providers/{provider}",
    response_model=ProviderStatus,
    responses={
        400: {"description": "Key validation failed"},
        401: {"description": "Authentication required"},
        422: {"description": "Unknown provider id"},
        501: {"description": "Provider scaffolded but not yet supported (v0.7.0)"},
    },
)
async def upsert_provider(
    provider: str,
    body: ProviderUpsertRequest,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> ProviderStatus:
    """Upsert + validate a tenant BYOK credential.

    Validation pre-flight: a single zero-cost ``/v1/models`` call with
    the candidate key. A 401/403 from the provider becomes a clean 400
    here ("key validation failed"). Other failures (network, timeout)
    also become 400 — we never persist a key we couldn't validate.
    """
    _require_known_provider(provider)
    if provider not in _VALIDATED_PROVIDERS:
        raise _ProviderNotShippedError(
            f"provider {provider!r} is scaffolded but not yet supported; "
            "v0.7.0 will ship full provider expansion. v0.3.0 supports "
            "anthropic only.",
            provider=provider,
            shipped_in="v0.7.0",
        )

    if not await _validate_anthropic_key(body.api_key):
        raise ValidationError(
            "Anthropic key validation failed: the provider rejected this key. "
            "Confirm the key is active, has the expected scopes, and was not "
            "rotated since you copied it.",
            provider=provider,
        )

    creds = TenantProviderCredentialRepo(repos.session, repos.encryptor)
    # Track whether this is a fresh credential or a rotation so the
    # audit log is precise — UI and downstream alerting key off the
    # action name.
    existing = await creds.list_for_tenant(
        repos.tenant.id, provider=provider, include_inactive=False
    )
    is_rotation = bool(existing)

    row = await creds.upsert(
        tenant_id=repos.tenant.id,
        provider=provider,
        plaintext_api_key=body.api_key,
        dek=repos.dek,
        model_overrides=body.model_overrides,
        region=body.region,
    )

    await repos.audit.append(
        tenant_id=repos.tenant.id,
        actor_type="api_key",
        actor_id_hash="",
        action="provider.byok_rotated" if is_rotation else "provider.byok_created",
        resource_type="tenant_provider_credential",
        resource_id=str(row.id),
        metadata={
            "provider": provider,
            # Last-4 redaction makes the audit useful for the tenant
            # ("the key ending XXXX was set"); the cleartext key never
            # appears here.
            "api_key_redacted": _redact_key(body.api_key),
        },
    )
    await repos.session.commit()

    return ProviderStatus(
        # Pydantic coerces the str → ``ProviderId`` literal at the model
        # boundary; ``provider`` was the path-param Literal we validated
        # at the top of this handler so the value is known-good.
        provider=row.provider,
        active=row.active,
        api_key_redacted=_redact_key(body.api_key),
        region=row.region,
        rotated_at=row.rotated_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


# ─── DELETE /v1/tenant/providers/{provider} ──────────────────────────


@router.delete(
    "/tenant/providers/{provider}",
    status_code=204,
    responses={
        401: {"description": "Authentication required"},
        422: {"description": "Unknown provider id"},
    },
)
async def revoke_provider(
    provider: str,
    repos: Annotated[RequestRepos, Depends(get_repos)],
) -> Response:
    """Soft-disable the active credential. Idempotent: 204 either way.

    Auditing only fires when a row was actually disabled. Re-deleting a
    soft-disabled row is silent — it's the natural shape of a "make
    sure nothing is active" intent."""
    _require_known_provider(provider)
    creds = TenantProviderCredentialRepo(repos.session, repos.encryptor)
    disabled = await creds.disable(tenant_id=repos.tenant.id, provider=provider)
    if disabled:
        await repos.audit.append(
            tenant_id=repos.tenant.id,
            actor_type="api_key",
            actor_id_hash="",
            action="provider.byok_revoked",
            resource_type="tenant_provider_credential",
            resource_id="",
            metadata={"provider": provider},
        )
    await repos.session.commit()
    return Response(status_code=204)


__all__ = ["router"]

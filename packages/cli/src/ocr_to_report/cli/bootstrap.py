"""``ocr-to-report bootstrap`` — local-dev tenant + API-key seeder.

Connects to the configured DATABASE_URL, creates the tables if they
don't exist, inserts a tenant + a single API key with the
``transcripts:write`` scope, and prints the plaintext key once.

Production tenant provisioning runs through a control-plane (Phase 13);
this command exists so a fresh ``docker compose up`` can be exercised
end-to-end without writing SQL.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Annotated

import typer

app = typer.Typer(
    name="bootstrap",
    help="Seed a tenant + API key (dev only).",
    no_args_is_help=False,
)


@app.callback(invoke_without_command=True)
def bootstrap(
    name: Annotated[str, typer.Option("--name", help="Tenant name")] = "Acme",
    slug: Annotated[str, typer.Option("--slug", help="Tenant slug (URL-safe id)")] = "acme",
    database_url: Annotated[
        str | None,
        typer.Option("--database-url", help="Override OCR2R_DATABASE_URL"),
    ] = None,
    sla_tier: Annotated[
        str,
        typer.Option("--sla-tier", help="economy / standard / premium / enterprise"),
    ] = "standard",
    admin: Annotated[
        bool,
        typer.Option(
            "--admin",
            help="Issue an admin:* scoped key (cross-tenant management).",
        ),
    ] = False,
) -> None:
    """Create the tenant + API key, print credentials."""
    asyncio.run(
        _run(
            name=name,
            slug=slug,
            database_url=database_url,
            sla_tier=sla_tier,
            admin=admin,
        )
    )


async def _run(
    *,
    name: str,
    slug: str,
    database_url: str | None,
    sla_tier: str,
    admin: bool = False,
) -> None:
    # Lazy imports so the dev command is fast when not running.
    from ocr_to_report.adapters.crypto import (  # noqa: PLC0415
        EnvelopeEncryptor,
        EnvKEKProvider,
    )
    from ocr_to_report.adapters.db import (  # noqa: PLC0415
        Base,
        get_engine,
        get_sessionmaker,
    )
    from ocr_to_report.adapters.db.repositories import (  # noqa: PLC0415
        ApiKeyRepo,
        TenantRepo,
    )

    if not os.environ.get("OCR2R_KEK_B64"):
        typer.secho(
            "OCR2R_KEK_B64 is unset — set it in .env or the environment first.",
            fg=typer.colors.RED,
            err=True,
        )
        sys.exit(2)

    db_url = database_url or os.environ.get("OCR2R_DATABASE_URL", "sqlite+aiosqlite:///./ocr2r.db")
    engine = get_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    encryptor = EnvelopeEncryptor(EnvKEKProvider(env_var="OCR2R_KEK_B64"))
    sm = get_sessionmaker(db_url)
    async with sm() as session:
        tenants = TenantRepo(session, encryptor)
        tenant, _dek = await tenants.create(name=name, slug=slug)
        tenant.sla_tier = sla_tier
        keys = ApiKeyRepo(session)
        scope_list = ["admin:*", "transcripts:write"] if admin else ["transcripts:write"]
        _row, plain_key = await keys.issue(
            tenant_id=tenant.id,
            scopes=scope_list,
        )
        await session.commit()

    typer.secho("Bootstrapped tenant + API key:", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  tenant_id : {tenant.id}")
    typer.echo(f"  tenant    : {name} ({slug}, sla={sla_tier})")
    typer.echo(f"  api_key   : {plain_key}")
    typer.echo()
    typer.secho(
        "Save the api_key now — it is hashed in the DB and cannot be recovered later.",
        fg=typer.colors.YELLOW,
    )


__all__ = ["app"]

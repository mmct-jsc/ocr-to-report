"""GET /v1/templates — list available targets / templates."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ocr_to_report.api.deps import AppState, get_app_state

router = APIRouter(prefix="/v1", tags=["templates"])


@router.get("/templates")
async def list_templates(
    state: Annotated[AppState, Depends(get_app_state)],
) -> dict[str, Any]:
    """List every target system + the template keys it ships."""
    out = [
        {
            "target_id": target.id,
            "name": target.manifest.name,
            "version": target.manifest.version,
            "output_language": target.manifest.output_language,
            "output_formats": target.manifest.output_formats,
            "templates": [
                {
                    "key": t.key,
                    "output_format": t.output_format,
                    "target_year_index": t.target_year_index,
                }
                for t in target.templates
            ],
        }
        for target in state.target_registry.all()
    ]
    return {"targets": out}


__all__ = ["router"]

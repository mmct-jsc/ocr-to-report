"""Renderer protocol + dispatch by output format."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ocr_to_report.core.errors.domain import OcrToReportError

if TYPE_CHECKING:
    from ocr_to_report.core.mapping import RenderData
    from ocr_to_report.core.target.bundle import TargetBundle


class RendererError(OcrToReportError):
    """Renderer failed (unsupported format, missing template, write error)."""

    status = 500
    type_uri = "https://errors.ocr-to-report/render-failed"
    title = "Render failed"


def render(
    target_bundle: TargetBundle,
    render_data: RenderData,
    *,
    bundle_root: str,
) -> bytes:
    """Dispatch on the chosen template's ``output_format``.

    ``bundle_root`` is the absolute filesystem path to the target bundle
    directory; the renderer reads template files from there.
    """
    template = next(
        (t for t in target_bundle.templates if t.key == render_data.template_key),
        None,
    )
    if template is None:
        raise RendererError(
            f"target bundle {target_bundle.id!r} has no template with key "
            f"{render_data.template_key!r}",
            target_id=target_bundle.id,
            template_key=render_data.template_key,
        )

    if template.output_format == "xlsx":
        # Lazy import keeps the protocol module light.
        from ocr_to_report.adapters.render.xlsx_renderer import (  # noqa: PLC0415
            render_xlsx,
        )

        return render_xlsx(target_bundle, render_data, bundle_root=bundle_root)

    raise RendererError(
        f"unsupported output_format {template.output_format!r}",
        output_format=template.output_format,
    )


__all__ = ["RendererError", "render"]

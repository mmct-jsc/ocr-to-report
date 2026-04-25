"""`python -m ocr_to_report.api` entrypoint."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    uvicorn.run(
        "ocr_to_report.api.app:app",
        host=os.getenv("OCR2R_API_HOST", "0.0.0.0"),  # noqa: S104 (containerized)
        port=int(os.getenv("OCR2R_API_PORT", "8000")),
        workers=int(os.getenv("OCR2R_API_WORKERS", "1")),
        reload=os.getenv("OCR2R_ENV", "production") == "development",
        access_log=False,
    )


if __name__ == "__main__":
    main()

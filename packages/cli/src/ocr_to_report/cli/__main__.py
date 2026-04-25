"""``python -m ocr_to_report.cli`` entrypoint."""

from __future__ import annotations

from ocr_to_report.cli.app import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()

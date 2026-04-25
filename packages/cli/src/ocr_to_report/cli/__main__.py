"""`python -m ocr_to_report.cli` entrypoint.

Phase 0: prints version. Phase 9 wires up the full Typer command tree.
"""

from __future__ import annotations

import sys

from ocr_to_report.cli import __version__


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] in {"-V", "--version"}:
        print(f"ocr-to-report {__version__}")  # noqa: T201
        return
    raise SystemExit("CLI not yet implemented (Phase 9). Try: ocr-to-report --version")


if __name__ == "__main__":
    main()

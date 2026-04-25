"""``python -m ocr_to_report.mcp`` / ``ocr-to-report-mcp`` entrypoint.

Boots the MCP server over stdio (the transport an MCP client like
Claude Desktop launches the process with). The actual tool wiring
lives in :mod:`ocr_to_report.mcp.server`.
"""

from __future__ import annotations

from ocr_to_report.mcp.server import build_server


def main() -> None:
    server = build_server()
    server.run()


if __name__ == "__main__":
    main()

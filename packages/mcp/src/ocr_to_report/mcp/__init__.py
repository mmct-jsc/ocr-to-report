"""OCR-to-Report MCP server.

Exposes the same v1 operations as the REST API + Python SDK as MCP
tools so AI agents can drive the platform without writing a custom
HTTP client. Built on FastMCP from the official ``mcp`` package.

The server is a thin shim over :class:`ocr_to_report.sdk_py.Client`:
each tool calls the SDK and returns the result. Auth + base URL come
from environment variables (``OCR2R_API_KEY`` / ``OCR2R_BASE_URL``).

Run via ``ocr-to-report-mcp`` (stdio transport) once installed; this
is what an MCP-compatible client (Claude Desktop, etc.) launches.
"""

from ocr_to_report.mcp.server import build_server

__all__ = ["build_server"]
__version__ = "0.1.0"

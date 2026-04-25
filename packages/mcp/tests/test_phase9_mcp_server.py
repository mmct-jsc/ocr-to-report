"""Phase 9 — MCP tool registration smoke tests.

The actual transport (stdio JSON-RPC) is FastMCP's responsibility; we
verify the server registers every expected tool with sane metadata.
This is what an MCP client introspects when listing tools — getting
this right is what makes the agent UI usable.
"""

from __future__ import annotations

import asyncio

import pytest

from ocr_to_report.mcp.server import build_server


@pytest.fixture
def server() -> object:
    return build_server()


_EXPECTED_TOOL_NAMES = {
    "process_transcript",
    "submit_batch",
    "get_job",
    "list_jobs",
    "approve_job",
    "reject_job",
    "list_templates",
    "get_usage",
    "create_webhook",
    "list_webhooks",
}


def _list_tool_names(server: object) -> set[str]:
    """Pull tool names off the FastMCP server.

    FastMCP exposes tools via ``list_tools`` (async) — block on it for
    the test. The shape is a list of ``Tool`` objects with a ``name``.
    """
    tools = asyncio.run(server.list_tools())  # type: ignore[attr-defined]
    return {tool.name for tool in tools}


def test_every_expected_tool_is_registered(server: object) -> None:
    names = _list_tool_names(server)
    missing = _EXPECTED_TOOL_NAMES - names
    assert not missing, f"missing MCP tools: {sorted(missing)}"


def test_no_extra_unexpected_tools(server: object) -> None:
    """Catch accidental additions; the public surface must stay deliberate."""
    names = _list_tool_names(server)
    unexpected = names - _EXPECTED_TOOL_NAMES
    assert not unexpected, f"unexpected MCP tools registered: {sorted(unexpected)}"


def test_server_name_is_ocr_to_report(server: object) -> None:
    assert server.name == "ocr-to-report"  # type: ignore[attr-defined]


def test_each_tool_has_a_description(server: object) -> None:
    tools = asyncio.run(server.list_tools())  # type: ignore[attr-defined]
    for tool in tools:
        assert tool.description, f"tool {tool.name!r} has no description"

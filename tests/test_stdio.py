"""The way an MCP client actually starts it: a subprocess, spoken to over stdio."""

from __future__ import annotations

import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

pytestmark = pytest.mark.anyio


async def test_the_entry_point_serves_over_stdio():
    process = StdioServerParameters(command=sys.executable, args=["-m", "catalog_mcp"])
    async with Client(process) as client:
        tools = {t.name for t in (await client.list_tools()).tools}
        result = await client.call_tool("list_domains", {})
    assert "get_dataset" in tools
    assert [d["name"] for d in result.structured_content["domains"]] == [
        "finance",
        "fraud",
        "policy",
    ]

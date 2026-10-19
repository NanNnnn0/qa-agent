"""MCP stdio server exposing the QA platform tools.

Run with ``python -m nanobot.qa.mcp_server``. Register it in nanobot's
``tools.mcpServers`` config (or an Agent Plugin ``mcp.json``) when an external
MCP client should manage the same QA database as the WebUI.

The server reuses the built-in agent tools, so the tool names, schemas and
validation are identical no matter who calls them.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from nanobot.agent.tools.qa import (
    QaCaseTool,
    QaOverviewTool,
    QaProjectTool,
    QaRunTool,
    QaScriptTool,
    QaTaskTool,
)
from nanobot.qa.api_tools import api_tools

try:  # pragma: no cover - import shape depends on the installed mcp version
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "The MCP SDK is required for the QA MCP server: pip install 'mcp>=1.26'"
    ) from exc


def _instances() -> dict[str, Any]:
    return {
        tool.name: tool
        for tool in (
            QaOverviewTool(),
            QaProjectTool(),
            QaCaseTool(),
            QaScriptTool(),
            QaRunTool(),
            QaTaskTool(None),
            *api_tools(),
        )
    }


def _tool_specs() -> list[Any]:
    specs: list[Any] = []
    for name, tool in _instances().items():
        function = tool.to_schema()["function"]
        specs.append(types.Tool(
            name=name,
            description=function["description"],
            inputSchema=function["parameters"],
        ))
    return specs


server: Server = Server("qa-agent")


@server.list_tools()
async def list_tools() -> list[Any]:
    return _tool_specs()


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any] | None = None) -> list[Any]:
    tools = _instances()
    tool = tools.get(name)
    if tool is None:
        return [types.TextContent(type="text", text=f"Error: unknown tool '{name}'")]
    try:
        result = await tool.execute(**(arguments or {}))
    except Exception as exc:  # pragma: no cover - defensive for external clients
        return [types.TextContent(type="text", text=f"Error: {exc}")]
    text = str(result)
    if not isinstance(text, str):
        text = json.dumps(text, ensure_ascii=False)
    return [types.TextContent(type="text", text=text)]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


if __name__ == "__main__":
    asyncio.run(main())

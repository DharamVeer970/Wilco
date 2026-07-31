"""Wilco's tools as an MCP server, over stdio.

A second front door onto the same registry, not new plumbing: main.py still calls
mcp_tool.call() in-process, because putting JSON-RPC between two functions in one process
would only cost latency. Both read one REGISTRY, so a tool added for the voice loop shows
up here with no work.

Run it from an MCP client, not by hand:

    {"mcpServers": {"wilco": {"command": "python", "args": ["d:/Codes/Projects/Jarvis/mcp_server.py"]}}}
"""
import asyncio

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

import mcp_tool
from mcp_tool import gate

server = Server("wilco")


@server.list_tools()
async def list_tools():
    """The same schemas the voice loop sends, reshaped into MCP's field names."""
    return [Tool(name=t["function"]["name"],
                 description=t["function"]["description"],
                 inputSchema=t["function"]["parameters"])
            for t in mcp_tool.TOOLS]


@server.call_tool()
async def call_tool(name, arguments):
    gate.session.set(str(id(server.request_context.session)))
    # tools block on real keystrokes and PowerShell, so keep them off the event loop
    result = await asyncio.to_thread(mcp_tool.call, name, arguments)
    return [TextContent(type="text", text=result)]


async def _serve():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(_serve())

"""MCP server tools for Wilco — connects to external MCP servers.

Connects to HTTP-based MCP servers (like LangChain docs), lists their tools,
and registers them into Wilco's tool registry so the agent can call them.

Tools from external servers are prefixed with the server name using double underscore
as separator (e.g. docs-langchain__search_docs_by_lang_chain).

The plugin system (core/plugins.py) discovers tools by iterating module vars,
so each remote tool is exposed as a real module-level function.

Example:
    set WILCO_PLUGINS_ENABLED=1
    python -c "from plugins import plugin_mcp; plugin_mcp._refresh_tool_functions(); print('docs-langchain__search_docs_by_lang_chain' in vars(plugin_mcp))"
"""
import asyncio
import threading

# MCP server URLs — add more entries to add more servers
MCP_SERVERS = {
    "docs-langchain": "https://docs.langchain.com/mcp",
    "reference-langchain": "https://reference.langchain.com/mcp",
}

# Tools fetched from external MCP servers
_REMOTE_TOOLS = {}
_LOCK = threading.RLock()
_CONNECTED = False


async def _connect_server(name, url):
    """Connect to a single MCP server and list its tools."""
    try:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                return name, tools.tools
    except Exception as e:
        print(f"MCP: failed to connect to {name} ({url}): {e}")
        return name, []


async def _connect_all():
    """Connect to all configured MCP servers and collect their tools."""
    global _REMOTE_TOOLS
    tasks = [_connect_server(name, url) for name, url in MCP_SERVERS.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    with _LOCK:
        _REMOTE_TOOLS.clear()
        for result in results:
            if isinstance(result, Exception):
                continue
            server_name, tools = result
            for tool in tools:
                prefixed = f"{server_name}__{tool.name}"
                _REMOTE_TOOLS[prefixed] = {
                    "server": server_name,
                    "original_name": tool.name,
                    "description": tool.description or "",
                    "input_schema": tool.inputSchema if hasattr(tool, "inputSchema") else {},
                }


def _run_async(coro):
    """Run an async coroutine in a new event loop (for use from sync code)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _ensure_connected():
    """Connect to MCP servers if not already connected. Thread-safe."""
    global _CONNECTED
    with _LOCK:
        if _CONNECTED or not MCP_SERVERS:
            return
        _run_async(_connect_all())
        _CONNECTED = True


def _make_caller(prefixed_name, info):
    """Create a caller function for a remote tool."""
    def caller(**kwargs):
        return _call_remote_sync(info["server"], info["original_name"], kwargs)
    caller.__name__ = prefixed_name
    caller.__doc__ = f"[{info['server']}] {info['description']}"
    return caller


async def _call_remote(server_name, tool_name, arguments):
    """Call a remote tool on an MCP server."""
    url = MCP_SERVERS.get(server_name)
    if not url:
        return f"Server {server_name} not found."

    try:
        from mcp.client.streamable_http import streamablehttp_client
        from mcp import ClientSession

        async with streamablehttp_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments or {})
                parts = []
                for content in result.content:
                    if hasattr(content, "text"):
                        parts.append(content.text)
                return "\n".join(parts) if parts else "Tool returned no text."
    except Exception as e:
        return f"Remote tool call failed: {e}"


def _call_remote_sync(server_name, tool_name, arguments):
    """Synchronous wrapper for _call_remote."""
    return _run_async(_call_remote(server_name, tool_name, arguments))


def _get_tools():
    """Get all remote tools, connecting lazily on first call."""
    _ensure_connected()
    with _LOCK:
        return dict(_REMOTE_TOOLS)


# Public API for the plugin system
def list_mcp_tools():
    """List all available MCP tools from connected servers."""
    tools = _get_tools()
    if not tools:
        return "No MCP tools available. Check server connectivity."
    lines = []
    for name, info in tools.items():
        lines.append(f"{name}: {info['description']}")
    return "\n".join(lines)


def _refresh_tool_functions():
    """Refresh module-level tool functions from connected MCP servers.

    Creates a real module-level function for each remote tool so the plugin
    system (core/plugins.py) can discover them via vars(module).items().
    """
    tools = _get_tools()
    for prefixed_name, info in tools.items():
        caller = _make_caller(prefixed_name, info)
        globals()[prefixed_name] = caller


# Auto-refresh at module load time so tools are available to the plugin system
_refresh_tool_functions()

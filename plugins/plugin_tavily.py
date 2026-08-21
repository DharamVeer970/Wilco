"""Tavily web search tool for Wilco.

Uses the Tavily API to perform web searches. Add TAVILY_API_KEY to your .env file.

Example:
    set WILCO_PLUGINS_ENABLED=1
    python -c "import mcp_tool; print('tavily_search' in mcp_tool.REGISTRY)"
"""

import os
from tavily import TavilyClient


def tavily_search(query: str, search_depth: str = "basic", max_results: int = 5) -> str:
    """Search the web using Tavily API.

    Args:
        query: The search query string.
        search_depth: Either "basic" or "advanced". Default is "basic".
        max_results: Maximum number of results to return. Default is 5.

    Returns:
        String containing search results or error message.
    """
    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        return "Tavily API key not configured. Set TAVILY_API_KEY in .env."

    try:
        client = TavilyClient(api_key=api_key)
        response = client.search(
            query=query,
            search_depth=search_depth,
            max_results=max_results,
        )

        if not response or "results" not in response:
            return f"No search results found for: {query}"

        results = []
        for i, result in enumerate(response.get("results", []), 1):
            title = result.get("title", "")
            url = result.get("url", "")
            content = result.get("content", "")
            if title:
                results.append(f"{i}. {title}")
                if content:
                    results[-1] += f" - {content[:200]}"
                if url:
                    results[-1] += f" ({url})"

        if not results:
            return f"No search results found for: {query}"

        return f"Search results for '{query}':\n" + "\n".join(results)

    except Exception as e:
        return f"Tavily search error: {e}"

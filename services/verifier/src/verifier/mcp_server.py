"""MCP server exposing the KYB discovery cascade.

Provides tools for live company verification — give it a URL, get back
careers page, ATS platform, and contact info via the LangGraph cascade.

Usage (stdio transport):
    uv run python -m verifier.mcp_server

Configure in Claude Desktop / MCP client:
    {
        "mcpServers": {
            "blueprint-kyb": {
                "command": "uv",
                "args": ["run", "python", "-m", "verifier.mcp_server"],
                "cwd": "/path/to/blueprint"
            }
        }
    }
"""

import logging
import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright
from playwright_stealth import Stealth

log = logging.getLogger("verifier.mcp_server")

mcp = FastMCP("blueprint-kyb")

_stealth = Stealth()

# Ollama config from environment (optional — cascade degrades gracefully)
_OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL")
_OLLAMA_MODEL = os.getenv("VERIFIER_LLM_MODEL", "llama3")
_OLLAMA_VISION_MODEL = os.getenv("VERIFIER_VISION_MODEL")


@mcp.tool()
async def discover_company(
    url: str,
    company_name: str = "",
    use_langgraph: bool = True,
) -> dict[str, Any]:
    """Run the KYB discovery cascade on a company website.

    Navigates to the URL with a stealth browser, then runs a 4-layer
    escalation cascade to find careers pages and identify ATS platforms:

    1. Deterministic DOM scoring (semantic element analysis)
    2. LLM text classification (Ollama/Llama 3, if available)
    3. Vision model analysis (screenshot + badge annotation, if available)
    4. Probe fallback (/careers, /jobs, subdomain probing)

    After finding a careers page, runs 6-layer ATS detection across 25+
    platforms (Greenhouse, Lever, Workday, iCIMS, etc.).

    Also extracts contact info (email, phone) from the homepage and
    contact pages.

    Args:
        url: Company website URL (e.g. "https://example.com")
        company_name: Optional company name for logging context
        use_langgraph: Use LangGraph cascade (True) or original async (False)

    Returns:
        Dictionary with careers and contact signals:
        {
            "url": "https://example.com",
            "careers": {
                "careers_url": "https://example.com/careers",
                "ats_platform": "greenhouse",
                "ats_url": "https://boards.greenhouse.io/example"
            },
            "contact": {
                "contact_email": "info@example.com",
                "contact_phone": "+1-555-0100",
                "contact_page_url": "https://example.com/contact"
            }
        }
    """
    if use_langgraph:
        result = await _discover_langgraph(url, company_name)
    else:
        result = await _discover_original(url)

    return {
        "url": url,
        "company_name": company_name or None,
        "cascade": "langgraph" if use_langgraph else "original",
        **result,
    }


@mcp.tool()
async def get_cascade_graph() -> str:
    """Return the LangGraph discovery cascade as a Mermaid diagram.

    Useful for visualizing the 4-layer escalation flow and understanding
    which nodes and conditional edges make up the cascade.

    Returns:
        Mermaid diagram string (paste into any Mermaid renderer)
    """
    from verifier.graph.build import get_graph_mermaid

    return get_graph_mermaid()


async def _discover_langgraph(url: str, company_name: str) -> dict[str, Any]:
    """Run LangGraph discovery cascade with managed browser lifecycle."""
    from verifier.graph.build import discover_one_langgraph

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _stealth.apply_stealth_async(context)
        page = await context.new_page()
        try:
            return await discover_one_langgraph(
                page,
                url,
                company_name=company_name,
                ollama_base_url=_OLLAMA_BASE_URL,
                ollama_model=_OLLAMA_MODEL,
                ollama_vision_model=_OLLAMA_VISION_MODEL,
            )
        finally:
            await page.close()
            await context.close()
            await browser.close()


async def _discover_original(url: str) -> dict[str, Any]:
    """Run original discovery cascade with managed browser lifecycle."""
    from verifier.checks.discovery import _discover_one

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _stealth.apply_stealth_async(context)
        page = await context.new_page()
        try:
            return await _discover_one(
                page,
                url,
                ollama_base_url=_OLLAMA_BASE_URL,
                ollama_model=_OLLAMA_MODEL,
                ollama_vision_model=_OLLAMA_VISION_MODEL,
            )
        finally:
            await page.close()
            await context.close()
            await browser.close()


if __name__ == "__main__":
    mcp.run()

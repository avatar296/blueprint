"""Build the LangGraph discovery cascade.

Assembles the StateGraph with nodes, conditional edges, and optional
checkpointing.  The compiled graph replaces the hand-rolled cascade in
discovery.py's _discover_one() function.

Usage:
    graph = build_discovery_graph()
    result = await graph.ainvoke(initial_state(...), config={
        "configurable": {"page": playwright_page, ...}
    })
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from langgraph.graph import END, StateGraph
from playwright.async_api import Page, async_playwright
from playwright_stealth import Stealth

from verifier.graph.edges import (
    route_after_dom,
    route_after_llm,
    route_after_navigate,
    route_after_vision,
)
from verifier.graph.nodes import (
    entity_match,
    extract_contact,
    facebook_fallback,
    llm_classify,
    navigate_careers,
    navigate_homepage,
    probe_fallback,
    score_dom,
    vision_analyze,
)
from verifier.graph.state import DiscoveryState, initial_state, empty_careers, empty_contact

log = logging.getLogger("verifier.graph.build")

_COMPANY_TIMEOUT = 60  # seconds — total budget per company

_stealth = Stealth()


def build_discovery_graph() -> StateGraph:
    """Construct and compile the KYB discovery cascade graph.

    Returns a compiled LangGraph app ready for .ainvoke().
    """
    graph = StateGraph(DiscoveryState)

    # ── Add nodes ────────────────────────────────────────────────
    graph.add_node("navigate_homepage", navigate_homepage)
    graph.add_node("entity_match", entity_match)
    graph.add_node("score_dom", score_dom)
    graph.add_node("llm_classify", llm_classify)
    graph.add_node("vision_analyze", vision_analyze)
    graph.add_node("probe_fallback", probe_fallback)
    graph.add_node("navigate_careers", navigate_careers)
    graph.add_node("extract_contact", extract_contact)
    graph.add_node("facebook_fallback", facebook_fallback)

    # ── Entry point ──────────────────────────────────────────────
    graph.set_entry_point("navigate_homepage")

    # ── Conditional edges ────────────────────────────────────────
    graph.add_conditional_edges("navigate_homepage", route_after_navigate, {
        "facebook_fallback": "facebook_fallback",
        "entity_match": "entity_match",
        "__end__": END,
    })

    graph.add_edge("entity_match", "score_dom")

    graph.add_conditional_edges("score_dom", route_after_dom, {
        "navigate_careers": "navigate_careers",
        "llm_classify": "llm_classify",
        "probe_fallback": "probe_fallback",
    })

    graph.add_conditional_edges("llm_classify", route_after_llm, {
        "navigate_careers": "navigate_careers",
        "vision_analyze": "vision_analyze",
        "probe_fallback": "probe_fallback",
    })

    graph.add_conditional_edges("vision_analyze", route_after_vision, {
        "navigate_careers": "navigate_careers",
        "probe_fallback": "probe_fallback",
    })

    # After careers navigation or probe → extract contact → end
    graph.add_edge("navigate_careers", "extract_contact")
    graph.add_edge("probe_fallback", "extract_contact")
    graph.add_edge("extract_contact", END)
    graph.add_edge("facebook_fallback", END)

    return graph.compile()


def get_graph_mermaid() -> str:
    """Export the graph as a Mermaid diagram string."""
    app = build_discovery_graph()
    return app.get_graph().draw_mermaid()


async def discover_one_langgraph(
    page: Page,
    url: str,
    *,
    is_parked: bool = False,
    company_id: str = "",
    company_name: str = "",
    city: str | None = None,
    state_code: str | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
    vectorstore=None,
) -> dict[str, Any]:
    """Run the LangGraph discovery cascade for one company.

    Drop-in replacement for discovery.py's _discover_one().
    Returns {"careers": {...}, "contact": {...}} in the same format.
    """
    app = build_discovery_graph()

    state = initial_state(
        company_id=company_id,
        company_name=company_name,
        url=url,
        is_parked=is_parked,
        city=city,
        state_code=state_code,
    )

    config = {
        "configurable": {
            "page": page,
            "ollama_base_url": ollama_base_url,
            "ollama_model": ollama_model,
            "ollama_timeout": ollama_timeout,
            "ollama_vision_model": ollama_vision_model,
            "ollama_vision_timeout": ollama_vision_timeout,
            "vectorstore": vectorstore,
        },
    }

    result = await app.ainvoke(state, config=config)

    return {
        "careers": result.get("careers", empty_careers()),
        "contact": result.get("contact", empty_contact()),
    }


async def discover_batch_langgraph(
    companies: list[dict],
    *,
    concurrency: int = 5,
    website_results: dict | None = None,
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
    vectorstore=None,
    on_result=None,
) -> dict:
    """Batch discovery using the LangGraph cascade.

    Drop-in replacement for discovery.discover_batch().
    Same signature, same output format, same incremental on_result callback.
    """
    if not companies:
        return {}

    sem = asyncio.Semaphore(concurrency)
    results: dict = {}
    wr = website_results or {}

    # Filter eligible companies (same logic as discover_batch)
    eligible = []
    for c in companies:
        cid = c["id"]
        ws = wr.get(cid, {})
        is_reachable = ws.get("website_reachable", False)
        is_parked = ws.get("website_is_parked", False)
        if wr and not is_reachable and not is_parked:
            continue
        if not c.get("website") and not is_parked:
            continue
        eligible.append(c)

    skipped = len(companies) - len(eligible)
    if skipped:
        log.info("LangGraph discovery: %d eligible, %d skipped", len(eligible), skipped)

    done_count = 0
    total = len(eligible)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(ignore_https_errors=True)
        await _stealth.apply_stealth_async(context)

        async def _run(company: dict):
            nonlocal done_count
            cid = company["id"]
            url = company.get("website", "")
            name = company.get("name", "")
            city = company.get("city")
            state_code = company.get("state")

            ws = wr.get(cid, {})
            is_parked = ws.get("website_is_parked", False)

            async with sem:
                page = await context.new_page()
                t_start = asyncio.get_event_loop().time()
                try:
                    result = await asyncio.wait_for(
                        discover_one_langgraph(
                            page,
                            url,
                            is_parked=is_parked,
                            company_id=str(cid),
                            company_name=name,
                            city=city,
                            state_code=state_code,
                            ollama_base_url=ollama_base_url,
                            ollama_model=ollama_model,
                            ollama_timeout=ollama_timeout,
                            ollama_vision_model=ollama_vision_model,
                            ollama_vision_timeout=ollama_vision_timeout,
                            vectorstore=vectorstore,
                        ),
                        timeout=_COMPANY_TIMEOUT,
                    )
                    results[cid] = result
                    if on_result:
                        on_result(cid, result)

                    # Store in pgvector for future entity matching
                    if vectorstore:
                        await vectorstore.store_result(
                            name, company_id=str(cid),
                        )

                    elapsed = asyncio.get_event_loop().time() - t_start
                    c = result.get("careers", {})
                    ct = result.get("contact", {})
                    parts = []
                    if c.get("careers_url"):
                        parts.append("careers")
                    if c.get("ats_platform"):
                        parts.append(f"ats={c['ats_platform']}")
                    if ct.get("contact_email"):
                        parts.append("email")
                    if ct.get("contact_phone"):
                        parts.append("phone")
                    found = ", ".join(parts) if parts else "none"
                    log.info("[%d/%d] %s — %s (%.1fs) [langgraph]",
                             done_count + 1, total, name, found, elapsed)

                except asyncio.TimeoutError:
                    log.warning("[%d/%d] %s — TIMEOUT after %ds [langgraph]",
                                done_count + 1, total, name, _COMPANY_TIMEOUT)
                except Exception:
                    log.warning("[%d/%d] %s — ERROR [langgraph]",
                                done_count + 1, total, name, exc_info=True)
                finally:
                    done_count += 1
                    await page.close()

        tasks = [asyncio.create_task(_run(c)) for c in eligible]
        await asyncio.gather(*tasks, return_exceptions=True)

        await context.close()
        await browser.close()

    found_careers = sum(1 for r in results.values() if r["careers"].get("careers_url"))
    found_ats = sum(1 for r in results.values() if r["careers"].get("ats_platform"))
    found_email = sum(1 for r in results.values() if r["contact"].get("contact_email"))
    found_phone = sum(1 for r in results.values() if r["contact"].get("contact_phone"))

    log.info(
        "LangGraph discovery batch: %d checked — %d careers, %d ATS, %d email, %d phone",
        len(results), found_careers, found_ats, found_email, found_phone,
    )
    return results

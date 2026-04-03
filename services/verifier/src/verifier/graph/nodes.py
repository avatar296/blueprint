"""LangGraph node functions for the KYB discovery cascade.

Each node wraps existing functions from discovery.py — same logic, LangGraph
orchestration.  Nodes receive the full DiscoveryState and return a partial
dict that LangGraph merges back.

The Playwright page is passed via LangGraph's configurable mechanism:
    config["configurable"]["page"]
"""

from __future__ import annotations

import base64
import logging
import re
from typing import Any
from urllib.parse import urljoin

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from playwright.async_api import Page, Error as PlaywrightError

from verifier.checks.discovery import (
    _ATS_DOMAINS,
    _CAREERS_NEGATIVE_RE,
    _CAREERS_PAGE_RE,
    _LOGIN_SIGNAL_RE,
    _NAV_TIMEOUT,
    _ANNOTATE_ELEMENTS_JS,
    _REMOVE_ANNOTATIONS_JS,
    _best_element,
    _build_llm_prompt,
    _build_vision_prompt,
    _clean_email,
    _clean_phone,
    _detect_ats_in_hrefs,
    _detect_ats_in_url,
    _extract_contact_from_text,
    _extract_jsonld_contact,
    _extract_navigable_elements,
    _extract_page_data,
    _facebook_extract_contact,
    _navigate_and_detect_ats,
    _prepare_elements_for_llm,
    _resolve_href,
    _root_domain,
    _score_for_careers,
    _score_for_contact,
    _validate_llm_pick,
)
from verifier.graph.state import DiscoveryState, empty_careers, empty_contact

log = logging.getLogger("verifier.graph.nodes")

# Re-use the LLM system prompts from discovery.py
_LLM_SYSTEM_PROMPT = (
    "You pick the best navigation element from a webpage for a given goal. "
    "Reply with ONLY the element number (e.g. '7') or 'NONE' if no element matches. "
    "Do not explain."
)

_VISION_SYSTEM_PROMPT = (
    "You are analyzing a screenshot of a webpage. Red numbered badges have been "
    "overlaid on navigable elements (links and buttons). "
    "Reply with ONLY the badge number (e.g. '7') of the best matching element, "
    "or 'NONE' if no element matches the goal. Do not explain."
)

_LLM_PICK_RE = re.compile(r"^\s*(\d+)\s*$")


def _get_page(config: RunnableConfig) -> Page:
    """Extract the Playwright page from LangGraph configurable."""
    return config["configurable"]["page"]


def _get_ollama_url(config: RunnableConfig) -> str | None:
    return config["configurable"].get("ollama_base_url")


def _get_ollama_model(config: RunnableConfig) -> str:
    return config["configurable"].get("ollama_model", "llama3")


def _get_vision_model(config: RunnableConfig) -> str | None:
    return config["configurable"].get("ollama_vision_model")


def _parse_llm_content(content: str, candidates: list[dict]) -> dict | None:
    """Parse the LLM response text into a candidate element."""
    content = content.strip()
    if content.upper() == "NONE":
        return None

    m = _LLM_PICK_RE.match(content)
    if not m:
        numbers = re.findall(r"\b(\d+)\b", content)
        if not numbers:
            log.debug("LLM returned unparseable response: %r", content)
            return None
        idx = int(numbers[0])
    else:
        idx = int(m.group(1))

    if 0 <= idx < len(candidates):
        return candidates[idx]

    log.debug("LLM returned out-of-range index %d (max %d)", idx, len(candidates) - 1)
    return None


# ── Node: navigate_homepage ──────────────────────────────────────


async def navigate_homepage(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Navigate to the company homepage, extract DOM elements and page data."""
    page = _get_page(config)
    url = state["url"]

    if not url:
        return {"nav_failed": True, "careers": empty_careers(), "contact": empty_contact()}

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT)
        if not resp or resp.status >= 400:
            return {"nav_failed": True}
    except PlaywrightError as exc:
        log.debug("Navigation failed for %s: %s", url, exc)
        return {"nav_failed": True}

    base_url = page.url
    base_domain = _root_domain(base_url)
    elements = await _extract_navigable_elements(page)
    page_data = await _extract_page_data(page)

    return {
        "base_url": base_url,
        "base_domain": base_domain,
        "nav_failed": False,
        "elements": elements,
        "page_data": page_data,
    }


# ── Node: score_dom ──────────────────────────────────────────────


async def score_dom(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Layer 1: Deterministic DOM scoring for careers + contact elements."""
    elements = state.get("elements", [])
    base_domain = state.get("base_domain", "")

    best_careers_el = _best_element(
        elements, lambda el: _score_for_careers(el, base_domain=base_domain),
    )
    best_contact_el = _best_element(elements, _score_for_contact)

    # Also check homepage URL and hrefs for ATS
    careers = state.get("careers", empty_careers())
    base_url = state.get("base_url", "")
    page_data = state.get("page_data", {})

    platform, ats_url = _detect_ats_in_url(base_url)
    if platform:
        careers = {**careers, "ats_platform": platform, "ats_url": ats_url}

    if not careers.get("ats_platform"):
        platform, ats_url = _detect_ats_in_hrefs(page_data.get("hrefs", []))
        if platform:
            careers = {**careers, "ats_platform": platform, "ats_url": ats_url}

    result: dict[str, Any] = {
        "best_careers_el": best_careers_el,
        "best_contact_el": best_contact_el,
        "careers": careers,
    }
    if best_careers_el:
        result["careers_source"] = "dom"

    return result


# ── Node: llm_classify ───────────────────────────────────────────


async def llm_classify(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Layer 2: LLM text classification via LangChain ChatOllama."""
    elements = state.get("elements", [])
    ollama_url = _get_ollama_url(config)
    model_name = _get_ollama_model(config)

    if not elements or not ollama_url:
        return {}

    result: dict[str, Any] = {}

    # Careers pick
    if not state.get("best_careers_el"):
        el = await _langchain_pick_element(
            elements, "careers", ollama_url, model_name, config,
        )
        if el and _validate_llm_pick(el, "careers"):
            result["best_careers_el"] = el
            result["careers_source"] = "llm"
            log.info("LLM picked careers: text=%r href=%r", el.get("text", ""), el.get("href", ""))
        elif el:
            log.debug("LLM careers pick rejected: text=%r href=%r", el.get("text", ""), el.get("href", ""))

    # Contact pick
    if not state.get("best_contact_el"):
        el = await _langchain_pick_element(
            elements, "contact", ollama_url, model_name, config,
        )
        if el:
            result["best_contact_el"] = el
            log.info("LLM picked contact: text=%r href=%r", el.get("text", ""), el.get("href", ""))

    return result


async def _langchain_pick_element(
    elements: list[dict],
    goal: str,
    ollama_url: str,
    model_name: str,
    config: RunnableConfig,
) -> dict | None:
    """Use LangChain ChatOllama to pick a navigation element."""
    candidates = _prepare_elements_for_llm(elements)
    if not candidates:
        return None

    prompt_text = _build_llm_prompt(candidates, goal)
    timeout = config["configurable"].get("ollama_timeout", 10.0)

    try:
        llm = ChatOllama(
            model=model_name,
            base_url=ollama_url,
            temperature=0,
            num_predict=50,
            timeout=timeout,
        )
        response = await llm.ainvoke([
            SystemMessage(content=_LLM_SYSTEM_PROMPT),
            HumanMessage(content=prompt_text),
        ])
        return _parse_llm_content(response.content, candidates)
    except Exception:
        log.debug("LangChain Ollama call failed for %s pick", goal, exc_info=True)
        return None


# ── Node: vision_analyze ─────────────────────────────────────────


async def vision_analyze(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Layer 3: Vision model screenshot analysis via LangChain ChatOllama."""
    elements = state.get("elements", [])
    ollama_url = _get_ollama_url(config)
    vision_model = _get_vision_model(config)
    page = _get_page(config)

    if not elements or not ollama_url or not vision_model:
        return {}

    result: dict[str, Any] = {}

    # Careers pick
    if not state.get("best_careers_el"):
        el = await _langchain_vision_pick(
            page, elements, "careers", ollama_url, vision_model, config,
        )
        if el and _validate_llm_pick(el, "careers"):
            result["best_careers_el"] = el
            result["careers_source"] = "vision"
            log.info("Vision picked careers: text=%r href=%r", el.get("text", ""), el.get("href", ""))
        elif el:
            log.debug("Vision careers pick rejected: text=%r href=%r", el.get("text", ""), el.get("href", ""))

    # Contact pick
    if not state.get("best_contact_el"):
        el = await _langchain_vision_pick(
            page, elements, "contact", ollama_url, vision_model, config,
        )
        if el:
            result["best_contact_el"] = el
            log.info("Vision picked contact: text=%r href=%r", el.get("text", ""), el.get("href", ""))

    return result


async def _langchain_vision_pick(
    page: Page,
    elements: list[dict],
    goal: str,
    ollama_url: str,
    vision_model: str,
    config: RunnableConfig,
) -> dict | None:
    """Use LangChain ChatOllama with vision to pick a navigation element."""
    candidates = _prepare_elements_for_llm(elements)
    if not candidates:
        return None

    indices = [c["idx"] for c in candidates]

    # Annotate page with numbered badges
    try:
        await page.evaluate(_ANNOTATE_ELEMENTS_JS, indices)
    except PlaywrightError:
        log.debug("Failed to inject vision badges", exc_info=True)
        return None

    # Take screenshot
    try:
        screenshot_bytes = await page.screenshot()
    except PlaywrightError:
        log.debug("Failed to take screenshot for vision", exc_info=True)
        return None
    finally:
        try:
            await page.evaluate(_REMOVE_ANNOTATIONS_JS)
        except PlaywrightError:
            pass

    b64_image = base64.b64encode(screenshot_bytes).decode("ascii")
    prompt_text = _build_vision_prompt(goal)
    timeout = config["configurable"].get("ollama_vision_timeout", 15.0)

    try:
        llm = ChatOllama(
            model=vision_model,
            base_url=ollama_url,
            temperature=0,
            num_predict=50,
            timeout=timeout,
        )
        response = await llm.ainvoke([
            SystemMessage(content=_VISION_SYSTEM_PROMPT),
            HumanMessage(content=[
                {"type": "text", "text": prompt_text},
                {"type": "image_url", "image_url": {
                    "url": f"data:image/png;base64,{b64_image}",
                }},
            ]),
        ])
        return _parse_llm_content(response.content, candidates)
    except Exception:
        log.debug("LangChain vision call failed for %s pick", goal, exc_info=True)
        return None


# ── Node: probe_fallback ─────────────────────────────────────────


async def probe_fallback(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Layer 4: Brute-force probe /careers, /jobs, subdomains."""
    page = _get_page(config)
    base_url = state.get("base_url", "")
    base_domain = state.get("base_domain", "")
    careers = state.get("careers", empty_careers())

    if careers.get("ats_platform"):
        # Already found ATS on homepage — skip probing
        return {"careers_source": "dom"}

    probe_urls = [urljoin(base_url, p) for p in ("/careers", "/jobs")]
    if base_domain:
        for sub in ("careers", "jobs"):
            probe_urls.append(f"https://{sub}.{base_domain}/")

    for probe_url in probe_urls:
        try:
            probe_resp = await page.goto(
                probe_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT,
            )
            if not probe_resp or probe_resp.status >= 400:
                continue

            final_url = page.url

            # Reject off-domain redirects (unless ATS)
            if base_domain:
                probe_domain = _root_domain(final_url)
                if probe_domain and probe_domain != base_domain:
                    if not any(ats in probe_domain for ats in _ATS_DOMAINS):
                        continue

            # Check page content for careers signals
            try:
                probe_title = await page.title()
                probe_snippet = await page.inner_text("body", timeout=3000)
                probe_snippet = probe_snippet[:5000]
            except PlaywrightError:
                probe_title = ""
                probe_snippet = ""

            probe_text = f"{probe_title} {probe_snippet}"

            if _LOGIN_SIGNAL_RE.search(probe_text) and not _CAREERS_PAGE_RE.search(probe_text):
                continue

            if not _CAREERS_PAGE_RE.search(probe_text):
                if _CAREERS_NEGATIVE_RE.search(probe_text):
                    continue

            # Detect ATS on the probed page
            ats_result = {"careers_url": final_url, "ats_platform": None, "ats_url": None}
            p, a = _detect_ats_in_url(final_url)
            if p:
                ats_result["ats_platform"] = p
                ats_result["ats_url"] = a
            else:
                ats_result.update(await _navigate_and_detect_ats(
                    page, final_url, base_domain=base_domain,
                ))

            return {
                "careers": ats_result,
                "careers_source": "probe",
            }
        except PlaywrightError:
            continue

    return {"careers_source": "none"}


# ── Node: navigate_careers ───────────────────────────────────────


async def navigate_careers(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Follow the best careers element and run ATS detection."""
    page = _get_page(config)
    best_el = state.get("best_careers_el")
    base_url = state.get("base_url", "")
    base_domain = state.get("base_domain", "")
    careers = state.get("careers", empty_careers())

    if not best_el:
        return {}

    careers_href = _resolve_href(best_el.get("href", ""), base_url)
    if not careers_href:
        return {}

    ats_result = await _navigate_and_detect_ats(
        page, careers_href, base_domain=base_domain,
    )

    updated_careers = {**careers}
    updated_careers["careers_url"] = ats_result["careers_url"]
    if ats_result["ats_platform"]:
        updated_careers["ats_platform"] = ats_result["ats_platform"]
        updated_careers["ats_url"] = ats_result["ats_url"]

    return {"careers": updated_careers}


# ── Node: extract_contact ────────────────────────────────────────


async def extract_contact(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Extract contact info from homepage and contact/about pages."""
    page = _get_page(config)
    page_data = state.get("page_data", {})
    base_url = state.get("base_url", "")
    best_contact_el = state.get("best_contact_el")
    contact = state.get("contact", empty_contact())

    # Step 1: Homepage mailto/tel links
    for raw in page_data.get("mailto", []):
        e = _clean_email(raw)
        if e:
            contact = {**contact, "contact_email": e}
            break

    for raw in page_data.get("tel", []):
        p = _clean_phone(raw)
        if p:
            contact = {**contact, "contact_phone": p}
            break

    # Step 2: JSON-LD
    if not contact.get("contact_email") or not contact.get("contact_phone"):
        jld_email, jld_phone = _extract_jsonld_contact(page_data.get("jsonld", []))
        if jld_email and not contact.get("contact_email"):
            contact = {**contact, "contact_email": jld_email}
        if jld_phone and not contact.get("contact_phone"):
            contact = {**contact, "contact_phone": jld_phone}

    # Step 3: Body text
    if not contact.get("contact_email") or not contact.get("contact_phone"):
        text_email, text_phone = _extract_contact_from_text(page_data.get("text", ""))
        if text_email and not contact.get("contact_email"):
            contact = {**contact, "contact_email": text_email}
        if text_phone and not contact.get("contact_phone"):
            contact = {**contact, "contact_phone": text_phone}

    # Step 4: Navigate to contact/about page if no email yet
    if not contact.get("contact_email"):
        contact = await _probe_contact_pages(page, contact, base_url, best_contact_el)

    return {"contact": contact}


async def _probe_contact_pages(
    page: Page,
    contact: dict,
    base_url: str,
    best_contact_el: dict | None,
) -> dict:
    """Navigate to contact pages and extract email/phone."""
    probe_urls: list[str] = []
    if best_contact_el:
        href = _resolve_href(best_contact_el.get("href", ""), base_url)
        if href:
            probe_urls.append(href)
    probe_urls.extend([
        urljoin(base_url, "/contact"),
        urljoin(base_url, "/contact-us"),
    ])

    # Deduplicate
    seen: set[str] = set()
    unique: list[str] = []
    for u in probe_urls:
        if u not in seen:
            seen.add(u)
            unique.append(u)

    for probe_url in unique:
        try:
            resp = await page.goto(
                probe_url, wait_until="domcontentloaded", timeout=_NAV_TIMEOUT,
            )
            if not resp or resp.status >= 400:
                continue

            cdata = await _extract_page_data(page)

            for raw in cdata.get("mailto", []):
                e = _clean_email(raw)
                if e:
                    contact = {**contact, "contact_email": e, "contact_page_url": page.url}
                    break

            for raw in cdata.get("tel", []):
                p = _clean_phone(raw)
                if p:
                    if not contact.get("contact_phone"):
                        contact = {**contact, "contact_phone": p}
                    if not contact.get("contact_page_url"):
                        contact = {**contact, "contact_page_url": page.url}
                    break

            if not contact.get("contact_email"):
                ce, cp = _extract_contact_from_text(cdata.get("text", ""))
                if ce:
                    contact = {**contact, "contact_email": ce, "contact_page_url": page.url}
                if cp and not contact.get("contact_phone"):
                    contact = {**contact, "contact_phone": cp}
                    if not contact.get("contact_page_url"):
                        contact = {**contact, "contact_page_url": page.url}

            if contact.get("contact_email"):
                break
        except PlaywrightError:
            continue

    return contact


# ── Node: facebook_fallback ──────────────────────────────────────


async def facebook_fallback(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Parked domain fallback: extract contact from Facebook About page."""
    page = _get_page(config)
    company_name = state.get("company_name", "")
    city = state.get("city")
    state_code = state.get("state_code")

    if not company_name:
        return {"contact": empty_contact()}

    fb_contact = await _facebook_extract_contact(page, company_name, city, state_code)
    contact = empty_contact()
    contact.update(fb_contact)

    return {"contact": contact}


# ── Node: entity_match ───────────────────────────────────────────


async def entity_match(
    state: DiscoveryState, config: RunnableConfig,
) -> dict[str, Any]:
    """Query pgvector for similar previously-verified companies."""
    vectorstore = config["configurable"].get("vectorstore")
    if not vectorstore:
        return {"similar_companies": []}

    company_name = state.get("company_name", "")
    if not company_name:
        return {"similar_companies": []}

    try:
        similar = await vectorstore.query_similar(company_name, k=3)
        return {"similar_companies": similar}
    except Exception:
        log.debug("pgvector query failed for %s", company_name, exc_info=True)
        return {"similar_companies": []}

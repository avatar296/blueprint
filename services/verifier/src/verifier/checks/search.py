"""DuckDuckGo search checks — web search, Facebook, Yelp, Google Maps."""

import asyncio
import logging
import re
import time

from ddgs import DDGS
from ddgs.exceptions import RatelimitException

log = logging.getLogger("verifier.checks.search")

# Shared rate limiter — minimum seconds between DDG calls
_MIN_INTERVAL = 1.1
_last_call_time = 0.0
_lock = asyncio.Lock()

_CLOSED_RE = re.compile(
    r"\bclosed\b|permanently\s+closed|cease[d]?\s+operations?|out\s+of\s+business",
    re.IGNORECASE,
)

_LEGAL_SUFFIXES_RE = re.compile(
    r",?\s*\b(Inc\.?|Corp\.?|Corporation|LLC\.?|L\.?L\.?C\.?"
    r"|Ltd\.?|L\.?P\.?|Co\.?|Company|P\.?C\.?|P\.?L\.?L\.?C\.?"
    r"|LLP|L\.?L\.?P\.?|D/?B/?A|Incorporated)\b\.?",
    re.IGNORECASE,
)


async def _rate_limit():
    """Enforce minimum interval between DDG API calls."""
    global _last_call_time
    async with _lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL - (now - _last_call_time)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_time = time.monotonic()


def _clean_name(name: str) -> str:
    """Strip legal suffixes and clean up a company name for search."""
    cleaned = _LEGAL_SUFFIXES_RE.sub("", name).strip(" ,.-")
    # Collapse extra whitespace
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or name


def _build_query(name: str, city: str | None, state: str | None) -> str:
    """Build a location-qualified search query."""
    parts = [_clean_name(name)]
    if city:
        parts.append(city)
    if state:
        parts.append(state)
    return " ".join(parts)


def _looks_closed(title: str, snippet: str) -> bool:
    """Check if a search result indicates the business is permanently closed."""
    text = f"{title} {snippet}"
    return bool(_CLOSED_RE.search(text))


async def search_web(name: str, city: str | None = None, state: str | None = None) -> dict:
    """General web search for a company.

    Returns dict with: search_result_count, search_top_snippet, search_top_url.
    """
    result = {
        "search_result_count": 0,
        "search_top_snippet": None,
        "search_top_url": None,
    }
    query = _build_query(name, city, state)

    try:
        await _rate_limit()
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=5))
        )
        result["search_result_count"] = len(results)
        if results:
            top = results[0]
            result["search_top_snippet"] = top.get("body", "")[:1000]
            result["search_top_url"] = top.get("href")
    except RatelimitException:
        raise
    except Exception:
        log.debug("Web search failed for %r", query, exc_info=True)

    return result


async def search_facebook(name: str, city: str | None = None, state: str | None = None) -> dict:
    """Search for a company's Facebook page.

    Returns dict with: facebook_url.
    """
    result = {"facebook_url": None}
    query = f'site:facebook.com "{name}"'
    if city:
        query += f" {city}"
    if state:
        query += f" {state}"

    try:
        await _rate_limit()
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=3))
        )
        # Skip non-business pages (marketplace, groups, events, etc.)
        _fb_skip = ("/marketplace", "/groups/", "/events/", "/watch/", "/gaming/", "/login")
        for r in results:
            href = r.get("href", "")
            if "facebook.com/" in href and not any(s in href for s in _fb_skip):
                result["facebook_url"] = href
                break
    except RatelimitException:
        raise
    except Exception:
        log.debug("Facebook search failed for %r", name, exc_info=True)

    return result


async def search_yelp(name: str, city: str | None = None, state: str | None = None) -> dict:
    """Search for a company's Yelp page.

    Returns dict with: yelp_url, yelp_closed.
    Yelp titles for closed businesses typically contain "CLOSED".
    """
    result: dict = {"yelp_url": None, "yelp_closed": None}
    query = f'site:yelp.com "{name}"'
    if city:
        query += f" {city}"
    if state:
        query += f" {state}"

    try:
        await _rate_limit()
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=3))
        )
        for r in results:
            href = r.get("href", "")
            if "yelp.com/biz/" in href:
                result["yelp_url"] = href
                title = r.get("title", "")
                snippet = r.get("body", "")
                result["yelp_closed"] = _looks_closed(title, snippet)
                break
    except RatelimitException:
        raise
    except Exception:
        log.debug("Yelp search failed for %r", name, exc_info=True)

    return result


async def search_maps(name: str, city: str | None = None, state: str | None = None) -> dict:
    """Search for a company's Google Maps listing via DDG text search.

    Returns dict with: gmaps_name, gmaps_closed.
    DDG `.maps()` was removed in v8; we fall back to a site-restricted text search
    which still surfaces the listing title and closed status from snippets.
    """
    result: dict = {"gmaps_name": None, "gmaps_closed": None}
    query = f'site:google.com/maps/place "{name}"'
    if city:
        query += f" {city}"
    if state:
        query += f" {state}"

    try:
        await _rate_limit()
        results = await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=3))
        )
        for r in results:
            href = r.get("href", "")
            # Only match actual business place pages, not search/community pages
            if "/maps/place/" in href:
                title = r.get("title", "")
                snippet = r.get("body", "")
                gmaps_name = re.sub(r"\s*[-·–—]\s*Google Maps$", "", title).strip()
                result["gmaps_name"] = gmaps_name or None
                result["gmaps_closed"] = _looks_closed(title, snippet)
                break
    except RatelimitException:
        raise
    except Exception:
        log.debug("Maps search failed for %r", name, exc_info=True)

    return result

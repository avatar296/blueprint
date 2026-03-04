"""Verification runner — orchestrates fast/slow signal checks and upserts.

Signals are persisted incrementally after each check phase so that a crash
mid-batch doesn't lose earlier results.
"""

import asyncio
import logging
import re
import time
from urllib.parse import urlparse

from common.signals import (
    get_companies_to_verify,
    insert_signals_batch,
)

from verifier.checks.discovery import discover_batch
from verifier.checks.search import search_facebook, search_maps, search_web, search_yelp
from verifier.checks.sec import check_sec_batch
from verifier.checks.website import check_websites_batch

log = logging.getLogger("verifier.runner")

_SUFFIXES = re.compile(
    r",?\s*\b(Inc\.?|Corp\.?|LLC|Ltd\.?|L\.?P\.?|Co\.?|Company"
    r"|Technologies|Technology|Group|Holdings|Solutions|Services"
    r"|Software|Labs|Laboratories|Systems|Enterprises?|International)\b\.?",
    re.IGNORECASE,
)


def _search_matches_company(
    name: str, search_url: str, snippet: str | None,
) -> bool:
    """Return True if the DDG result plausibly belongs to this company."""
    norm = _SUFFIXES.sub("", name).strip(" ,.-").lower()
    if not norm:
        return False
    # Check domain (strip punctuation so "pueblo-mechanical.com" matches "pueblo mechanical")
    domain = urlparse(search_url).netloc.lower().replace("-", " ").replace(".", " ")
    if norm in domain:
        return True
    # Check snippet text
    if snippet and norm in snippet.lower():
        return True
    return False


def _persist_phase(label: str, result_map: dict, check_type: str) -> int:
    """Persist one check-type's results and log the count."""
    rows = [(cid, check_type, res) for cid, res in result_map.items()]
    if not rows:
        return 0
    n = insert_signals_batch(rows)
    log.info("Persisted %d %s signals", n, label)
    return n


def _persist_one(company_id, check_type: str, result: dict) -> None:
    """Persist a single signal row immediately."""
    insert_signals_batch([(company_id, check_type, result)])


def run_verification(
    *,
    batch_size: int = 500,
    reverify_days: int = 30,
    website_concurrency: int = 50,
    ddg_limit: int = 1000,
    sec_concurrency: int = 10,
    discovery_concurrency: int = 5,
    ollama_base_url: str | None = None,
    ollama_model: str = "llama3",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
) -> int:
    """Run one verification cycle.

    Phases run with maximum parallelism:
      - Website liveness, SEC checks, and DDG/search all start concurrently
      - Discovery starts as soon as website liveness completes
      - Backfill runs after both discovery and search finish

    Signals are persisted after each phase completes so partial progress
    survives crashes.  Returns total signal rows inserted.
    """
    companies = get_companies_to_verify(limit=batch_size, reverify_days=reverify_days)
    if not companies:
        log.info("No companies to verify")
        return 0

    log.info("Verifying %d companies", len(companies))

    return asyncio.run(_run_all_phases(
        companies,
        website_concurrency=website_concurrency,
        ddg_limit=ddg_limit,
        sec_concurrency=sec_concurrency,
        discovery_concurrency=discovery_concurrency,
        ollama_base_url=ollama_base_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        ollama_vision_model=ollama_vision_model,
        ollama_vision_timeout=ollama_vision_timeout,
    ))


async def _run_all_phases(
    companies: list[dict],
    *,
    website_concurrency: int,
    ddg_limit: int,
    sec_concurrency: int,
    discovery_concurrency: int,
    ollama_base_url: str | None,
    ollama_model: str,
    ollama_timeout: float,
    ollama_vision_model: str | None,
    ollama_vision_timeout: float,
) -> int:
    inserted = 0
    t0 = time.monotonic()

    # ── Kick off independent phases concurrently ──────────────
    website_task = asyncio.create_task(
        check_websites_batch(companies, concurrency=website_concurrency),
        name="website",
    )
    sec_task = asyncio.create_task(
        check_sec_batch(companies, concurrency=sec_concurrency),
        name="sec",
    )
    search_task = asyncio.create_task(
        _search_pass(companies, ddg_limit),
        name="search",
    )

    # ── Phase 1: Website liveness (await first — discovery depends on it) ──
    website_results = await website_task
    inserted += _persist_phase("website", website_results, "website")
    log.info("Phase 1 done in %.1fs: %d website results", time.monotonic() - t0, len(website_results))

    # ── Phase 3: Discovery (needs website_results, runs alongside SEC + search) ──
    # Persist each company's careers + contact as soon as it finishes.
    def _on_discovery(cid, result):
        nonlocal inserted
        if result.get("careers"):
            _persist_one(cid, "careers", result["careers"])
            inserted += 1
        if result.get("contact"):
            _persist_one(cid, "contact", result["contact"])
            inserted += 1

    discovery_task = asyncio.create_task(
        discover_batch(
            companies,
            concurrency=discovery_concurrency,
            website_results=website_results,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_timeout=ollama_timeout,
            ollama_vision_model=ollama_vision_model,
            ollama_vision_timeout=ollama_vision_timeout,
            on_result=_on_discovery,
        ),
        name="discovery",
    )

    # ── Phase 2: SEC (probably done by now, but await to persist) ──
    sec_results = await sec_task
    inserted += _persist_phase("sec", sec_results, "sec")
    log.info("Phase 2 done: %d SEC results", len(sec_results))

    # ── Await discovery + search in parallel ──────────────────
    discovery, (web_results, fb_results, yelp_results, maps_results) = await asyncio.gather(
        discovery_task, search_task,
    )

    log.info(
        "Phase 3 + search done in %.1fs: %d discovery, %d web, %d fb, %d yelp, %d maps",
        time.monotonic() - t0,
        len(discovery), len(web_results), len(fb_results),
        len(yelp_results), len(maps_results),
    )

    # ── Phase 5: Backfill discovery for companies with search-found URLs ──
    backfill = []
    for c in companies:
        cid = c["id"]
        existing = discovery.get(cid, {}).get("careers", {})
        if existing.get("careers_url"):
            continue
        search_url = web_results.get(cid, {}).get("search_top_url")
        if not search_url:
            continue
        snippet = web_results.get(cid, {}).get("search_top_snippet")
        if not _search_matches_company(c["name"], search_url, snippet):
            log.debug("Backfill skip %s: search result doesn't match (%s)", c["name"], search_url)
            continue
        backfill.append({**c, "website": search_url})

    if backfill:
        log.info("Backfill discovery for %d companies with search-found URLs", len(backfill))
        backfill_discovery = await discover_batch(
            backfill,
            concurrency=discovery_concurrency,
            website_results=None,
            ollama_base_url=ollama_base_url,
            ollama_model=ollama_model,
            ollama_timeout=ollama_timeout,
            ollama_vision_model=ollama_vision_model,
            ollama_vision_timeout=ollama_vision_timeout,
            on_result=_on_discovery,
        )
        log.info("Backfill discovery found %d additional results", len(backfill_discovery))

    total_elapsed = time.monotonic() - t0
    log.info(
        "Verification complete in %.1fs: %d signal rows for %d companies"
        " (%d backfilled from search)",
        total_elapsed, inserted, len(companies), len(backfill) if backfill else 0,
    )
    return inserted


async def _search_pass(companies: list[dict], ddg_limit: int) -> tuple[dict, dict, dict, dict]:
    """Run DDG/Facebook/Yelp/Maps searches concurrently.

    Caps at 10 concurrent searches to avoid overwhelming DDG rate limits.
    Each company's search results are persisted immediately.
    """
    web: dict = {}
    fb: dict = {}
    yelp: dict = {}
    maps: dict = {}
    ddg_count = min(ddg_limit, len(companies))
    sem = asyncio.Semaphore(10)
    done = 0

    async def _search_company(company):
        nonlocal done
        cid = company["id"]
        name = company["name"]
        city = company.get("city")
        state = company.get("state")

        async with sem:
            try:
                web[cid] = await search_web(name, city, state)
                _persist_one(cid, "web_search", web[cid])
            except Exception:
                log.debug("Web search failed for %s", name, exc_info=True)
            try:
                fb[cid] = await search_facebook(name, city, state)
                _persist_one(cid, "facebook", fb[cid])
            except Exception:
                log.debug("Facebook search failed for %s", name, exc_info=True)
            try:
                yelp[cid] = await search_yelp(name, city, state)
                _persist_one(cid, "yelp", yelp[cid])
            except Exception:
                log.debug("Yelp search failed for %s", name, exc_info=True)
            try:
                maps[cid] = await search_maps(name, city, state)
                _persist_one(cid, "maps", maps[cid])
            except Exception:
                log.debug("Maps search failed for %s", name, exc_info=True)

        done += 1
        if done % 25 == 0 or done == ddg_count:
            log.info("Search progress: %d/%d companies", done, ddg_count)

    await asyncio.gather(*[
        _search_company(c) for c in companies[:ddg_count]
    ])
    return web, fb, yelp, maps

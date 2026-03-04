"""Verification runner — orchestrates fast/slow signal checks and upserts."""

import asyncio
import logging
import time

from common.signals import (
    get_companies_to_verify,
    insert_signals_batch,
    mark_verified_batch,
)

from verifier.checks.discovery import discover_batch
from verifier.checks.search import search_facebook, search_maps, search_web, search_yelp
from verifier.checks.sec import check_sec_batch
from verifier.checks.website import check_websites_batch

log = logging.getLogger("verifier.runner")


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

    1. Fast pass: website liveness + SEC checks (high parallelism)
    2. Slow pass: DDG web search + Facebook + Yelp + Maps (rate-limited)

    Each check type is inserted as its own row in company_signals.
    Returns total signal rows inserted.
    """
    companies = get_companies_to_verify(limit=batch_size, reverify_days=reverify_days)
    if not companies:
        log.info("No companies to verify")
        return 0

    log.info("Verifying %d companies", len(companies))

    # ── Fast pass: website + SEC + discovery ──────────────────────
    # SEC is independent; discovery depends on website_results for
    # parked-domain routing.  Run website first, then SEC || discovery.
    t0 = time.monotonic()

    async def _fast_pass():
        ws = await check_websites_batch(companies, concurrency=website_concurrency)

        async def _discovery():
            return await discover_batch(
                companies,
                concurrency=discovery_concurrency,
                website_results=ws,
                ollama_base_url=ollama_base_url,
                ollama_model=ollama_model,
                ollama_timeout=ollama_timeout,
                ollama_vision_model=ollama_vision_model,
                ollama_vision_timeout=ollama_vision_timeout,
            )

        sec, disc = await asyncio.gather(
            check_sec_batch(companies, concurrency=sec_concurrency),
            _discovery(),
        )
        return ws, sec, disc

    website_results, sec_results, discovery = asyncio.run(_fast_pass())
    careers_results = {cid: r["careers"] for cid, r in discovery.items()}
    contact_results = {cid: r["contact"] for cid, r in discovery.items()}

    fast_elapsed = time.monotonic() - t0
    log.info(
        "Fast pass: %d website, %d SEC, %d discovery in %.1fs",
        len(website_results),
        len(sec_results),
        len(discovery),
        fast_elapsed,
    )

    # ── Slow pass: DDG search + Facebook + Yelp + Maps ───────────
    # Single event loop so the asyncio.Lock rate limiter in search.py
    # works correctly across all concurrent coroutines.
    t1 = time.monotonic()
    ddg_count = min(ddg_limit, len(companies))

    async def _slow_pass():
        web: dict = {}
        fb: dict = {}
        yelp: dict = {}
        maps: dict = {}

        async def _search_company(company):
            cid = company["id"]
            name = company["name"]
            city = company.get("city")
            state = company.get("state")

            try:
                web[cid] = await search_web(name, city, state)
            except Exception:
                log.debug("Web search failed for %s", name, exc_info=True)
            try:
                fb[cid] = await search_facebook(name, city, state)
            except Exception:
                log.debug("Facebook search failed for %s", name, exc_info=True)
            try:
                yelp[cid] = await search_yelp(name, city, state)
            except Exception:
                log.debug("Yelp search failed for %s", name, exc_info=True)
            try:
                maps[cid] = await search_maps(name, city, state)
            except Exception:
                log.debug("Maps search failed for %s", name, exc_info=True)

        await asyncio.gather(*[
            _search_company(c) for c in companies[:ddg_count]
        ])
        return web, fb, yelp, maps

    web_results, fb_results, yelp_results, maps_results = asyncio.run(_slow_pass())

    slow_elapsed = time.monotonic() - t1
    log.info(
        "Slow pass: %d web, %d fb, %d yelp, %d maps in %.1fs",
        len(web_results),
        len(fb_results),
        len(yelp_results),
        len(maps_results),
        slow_elapsed,
    )

    # ── Insert one row per check type per company ─────────────────
    rows: list[tuple] = []
    all_company_ids = {c["id"] for c in companies}

    for cid in all_company_ids:
        if cid in website_results:
            rows.append((cid, "website", website_results[cid]))
        if cid in sec_results:
            rows.append((cid, "sec", sec_results[cid]))
        if cid in careers_results:
            rows.append((cid, "careers", careers_results[cid]))
        if cid in contact_results:
            rows.append((cid, "contact", contact_results[cid]))
        if cid in web_results:
            rows.append((cid, "web_search", web_results[cid]))
        if cid in fb_results:
            rows.append((cid, "facebook", fb_results[cid]))
        if cid in yelp_results:
            rows.append((cid, "yelp", yelp_results[cid]))
        if cid in maps_results:
            rows.append((cid, "maps", maps_results[cid]))

    inserted = 0
    if rows:
        inserted = insert_signals_batch(rows)

    # Mark all companies as verified (even those with no signals — we checked)
    mark_verified_batch(list(all_company_ids))

    log.info(
        "Verification complete: %d signal rows inserted, %d companies marked verified",
        inserted,
        len(all_company_ids),
    )
    return inserted

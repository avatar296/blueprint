"""SEC EDGAR EFTS check — recent filing lookup via the free public API."""

import asyncio
import logging
from datetime import date, timedelta

import httpx

log = logging.getLogger("verifier.checks.sec")

_EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)
_HEADERS = {
    "User-Agent": "Blueprint/1.0 (company-verification; contact@blueprint.dev)",
    "Accept": "application/json",
}


async def check_sec_filing(
    company_name: str, ticker: str | None = None
) -> dict:
    """Query SEC EDGAR EFTS for recent filings.

    Uses ticker if available, otherwise company name.

    Returns dict with: sec_last_filing_date, sec_filing_type.
    """
    result = {
        "sec_last_filing_date": None,
        "sec_filing_type": None,
    }

    query = ticker if ticker else f'"{company_name}"'
    today = date.today()
    start = today - timedelta(days=365)

    params = {
        "q": query,
        "dateRange": "custom",
        "startdt": start.isoformat(),
        "enddt": today.isoformat(),
    }

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT, headers=_HEADERS
        ) as client:
            resp = await client.get(_EFTS_URL, params=params)
            resp.raise_for_status()
            data = resp.json()

            hits = data.get("hits", {}).get("hits", [])
            if hits:
                source = hits[0].get("_source", {})
                filing_date = source.get("file_date")
                filing_type = source.get("form_type")
                if filing_date:
                    result["sec_last_filing_date"] = filing_date
                if filing_type:
                    result["sec_filing_type"] = filing_type

    except httpx.HTTPError:
        log.debug("SEC check failed for %r", query, exc_info=True)
    except Exception:
        log.debug("Unexpected error in SEC check for %r", query, exc_info=True)

    return result


async def check_sec_batch(
    companies: list[dict], *, concurrency: int = 10
) -> dict:
    """Check SEC filings for a batch of companies.

    Only processes companies with source='sec_edgar' or ticker IS NOT NULL.

    Args:
        companies: list of dicts with 'id', 'name', 'source', 'ticker' keys.
        concurrency: max parallel requests.

    Returns dict mapping company_id -> SEC result dict.
    """
    sem = asyncio.Semaphore(concurrency)
    results = {}

    # Filter to SEC-relevant companies
    sec_companies = [
        c for c in companies
        if c.get("source") == "sec_edgar" or c.get("ticker")
    ]

    if not sec_companies:
        return results

    async def _check(company: dict):
        async with sem:
            cid = company["id"]
            r = await check_sec_filing(company["name"], company.get("ticker"))
            if r["sec_last_filing_date"] or r["sec_filing_type"]:
                results[cid] = r

    tasks = [asyncio.create_task(_check(c)) for c in sec_companies]
    await asyncio.gather(*tasks, return_exceptions=True)

    log.info(
        "SEC batch: %d eligible, %d with filings",
        len(sec_companies),
        len(results),
    )
    return results

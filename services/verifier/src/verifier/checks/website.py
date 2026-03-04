"""Website liveness check — async httpx HEAD/GET with parked detection."""

import asyncio
import logging
import re

import httpx

log = logging.getLogger("verifier.checks.website")

_PARKED_PATTERNS = re.compile(
    r"domain for sale|buy this domain|parked free|godaddy|sedo\.com|"
    r"hugedomains|afternic|dan\.com|is for sale|this domain|"
    r"parking page|under construction|coming soon",
    re.IGNORECASE,
)

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)

# Timeout per request (connect + read)
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


async def check_website(url: str) -> dict:
    """Check a single website URL for liveness, redirects, title, parked status.

    Returns dict with keys: website_url, website_status, website_reachable,
    website_redirect_url, website_title, website_is_parked.
    """
    result = {
        "website_url": url,
        "website_status": None,
        "website_reachable": False,
        "website_redirect_url": None,
        "website_title": None,
        "website_is_parked": None,
    }

    if not url:
        return result

    # Ensure URL has a scheme
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            verify=False,  # noqa: S501 — many small-biz sites have bad certs
        ) as client:
            # Try HEAD first (lighter)
            try:
                resp = await client.head(url)
                if resp.status_code == 405:
                    resp = await client.get(url)
            except httpx.HTTPError:
                resp = await client.get(url)

            result["website_status"] = resp.status_code
            result["website_reachable"] = 200 <= resp.status_code < 400

            # Capture redirect URL if different from original
            final_url = str(resp.url)
            if final_url.rstrip("/") != url.rstrip("/"):
                result["website_redirect_url"] = final_url

            # Extract title and check for parked indicators from GET body
            body = ""
            if resp.request.method == "GET" and hasattr(resp, "text"):
                body = resp.text[:10_000]  # Only scan first 10KB
            elif result["website_reachable"]:
                # HEAD succeeded — do a quick GET for title/parked check
                try:
                    get_resp = await client.get(url)
                    body = get_resp.text[:10_000]
                except httpx.HTTPError:
                    pass

            if body:
                m = _TITLE_RE.search(body)
                if m:
                    result["website_title"] = m.group(1).strip()[:500]

                result["website_is_parked"] = bool(_PARKED_PATTERNS.search(body))

    except httpx.HTTPError as exc:
        log.debug("Website check failed for %s: %s", url, exc)
    except Exception:
        log.debug("Unexpected error checking %s", url, exc_info=True)

    return result


async def check_websites_batch(
    companies: list[dict], *, concurrency: int = 50
) -> dict:
    """Check websites for a batch of companies.

    Args:
        companies: list of dicts with 'id' and 'website' keys.
        concurrency: max parallel requests.

    Returns dict mapping company_id -> website result dict.
    """
    sem = asyncio.Semaphore(concurrency)
    results = {}

    async def _check(company: dict):
        async with sem:
            cid = company["id"]
            url = company.get("website")
            if not url:
                return
            r = await check_website(url)
            results[cid] = r

    tasks = [asyncio.create_task(_check(c)) for c in companies]
    await asyncio.gather(*tasks, return_exceptions=True)

    log.info(
        "Website batch: %d checked, %d reachable",
        len(results),
        sum(1 for r in results.values() if r.get("website_reachable")),
    )
    return results

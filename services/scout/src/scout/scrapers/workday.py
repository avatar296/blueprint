"""Workday ATS scraper — fetches jobs via the internal CXS JSON endpoint (no browser needed).

Workday career sites POST to /wday/cxs/{slug}/{site_path}/jobs and return JSON.
The board_id field in target_companies.json is packed as "slug:wdN:site_path"
(e.g. "lockheedmartin:wd5:search").
"""

import logging
import time

import httpx

from common.models import JobInsert
from scout.parsers import detect_remote, parse_relative_date
from scout.scrapers.catalog_base import CatalogScraper, TargetCompany

log = logging.getLogger("scout.scrapers.workday")

_PAGE_SIZE = 20
_TIMEOUT = 20.0
_PAGE_DELAY = 0.5


def _parse_board_id(board_id: str) -> tuple[str, str, str]:
    """Split board_id 'slug:wdN:site_path' into (slug, wdN, site_path)."""
    parts = board_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid Workday board_id format: {board_id!r} (expected slug:wdN:site_path)")
    return parts[0], parts[1], parts[2]


class WorkdayScraper(CatalogScraper):
    source_prefix = "workday"

    def scrape_company(self, company: TargetCompany) -> list[JobInsert]:
        slug, wd_instance, site_path = _parse_board_id(company.board_id)
        base_url = f"https://{slug}.{wd_instance}.myworkdayjobs.com"
        api_url = f"{base_url}/wday/cxs/{slug}/{site_path}/jobs"

        jobs: list[JobInsert] = []
        offset = 0

        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            # GET career page to establish session cookies
            try:
                client.get(f"{base_url}/en-US/{site_path}")
            except httpx.HTTPError:
                log.debug("Cookie prefetch failed for %s — continuing anyway", company.name)

            while True:
                payload = {
                    "appliedFacets": {},
                    "limit": _PAGE_SIZE,
                    "offset": offset,
                    "searchText": "",
                }

                try:
                    resp = client.post(api_url, json=payload)
                except httpx.HTTPError:
                    log.warning("HTTP error fetching %s page at offset %d", company.name, offset, exc_info=True)
                    break

                if resp.status_code != 200:
                    log.warning("Workday API returned %d for %s at offset %d", resp.status_code, company.name, offset)
                    break

                data = resp.json()
                total = data.get("total", 0)
                postings = data.get("jobPostings", [])

                if not postings:
                    break

                for posting in postings:
                    job = self._parse_posting(posting, company, base_url)
                    if job:
                        jobs.append(job)

                offset += len(postings)
                if offset >= total:
                    break

                time.sleep(_PAGE_DELAY)

        log.info("Workday %s: %d postings fetched", company.name, len(jobs))
        return jobs

    def _parse_posting(self, posting: dict, company: TargetCompany, base_url: str) -> JobInsert | None:
        title = posting.get("title", "").strip()
        external_path = posting.get("externalPath", "")
        if not title or not external_path:
            return None

        # Source ID is the external path (unique per posting)
        source_id = external_path.lstrip("/")
        url = f"{base_url}/en-US{external_path}"

        location = posting.get("locationsText", "")
        posted_on = posting.get("postedOn", "")
        date_posted = parse_relative_date(posted_on)

        remote = detect_remote(location, title)

        return JobInsert(
            source=f"workday:{company.board_id}",
            source_id=source_id,
            url=url,
            title=title,
            company=company.name,
            description=None,
            location=location or None,
            remote=remote,
            salary_min=None,
            salary_max=None,
            date_posted=date_posted,
        )

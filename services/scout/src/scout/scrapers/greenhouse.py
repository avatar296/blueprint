"""Greenhouse ATS scraper — fetches jobs via the public boards API (no browser needed)."""

import logging

import httpx

from common.models import JobInsert
from scout.parsers import detect_remote, parse_salary
from scout.scrapers.catalog_base import CatalogScraper, TargetCompany

log = logging.getLogger("scout.scrapers.greenhouse")

_API_BASE = "https://boards-api.greenhouse.io/v1/boards/{board_id}/jobs"
_TIMEOUT = 15.0


class GreenhouseScraper(CatalogScraper):
    source_prefix = "greenhouse"

    def scrape_company(self, company: TargetCompany) -> list[JobInsert]:
        url = _API_BASE.format(board_id=company.board_id)
        try:
            resp = httpx.get(url, params={"content": "true"}, timeout=_TIMEOUT)
        except httpx.HTTPError:
            log.warning("HTTP error fetching %s board '%s'", company.name, company.board_id, exc_info=True)
            return []

        if resp.status_code == 404:
            log.warning("Greenhouse board not found: %s (board_id=%s)", company.name, company.board_id)
            return []
        if resp.status_code != 200:
            log.warning("Greenhouse API returned %d for %s", resp.status_code, company.name)
            return []

        data = resp.json()
        postings = data.get("jobs", [])
        log.info("Greenhouse %s: %d postings", company.name, len(postings))

        jobs: list[JobInsert] = []
        for posting in postings:
            job = self._parse_posting(posting, company)
            if job:
                jobs.append(job)

        return jobs

    def _parse_posting(self, posting: dict, company: TargetCompany) -> JobInsert | None:
        title = posting.get("title", "").strip()
        job_id = posting.get("id")
        if not title or not job_id:
            return None

        location_name = ""
        if loc := posting.get("location", {}):
            location_name = loc.get("name", "")

        absolute_url = posting.get("absolute_url", "")

        # Greenhouse content field contains HTML description
        description = posting.get("content", "")

        salary_min, salary_max = None, None
        remote = detect_remote(location_name, title)

        return JobInsert(
            source=f"greenhouse:{company.board_id}",
            source_id=str(job_id),
            url=absolute_url,
            title=title,
            company=company.name,
            description=description,
            location=location_name or None,
            remote=remote,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=None,
        )

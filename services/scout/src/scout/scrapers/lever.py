"""Lever ATS scraper — fetches jobs via the public postings API (no browser needed)."""

import logging

import httpx

from common.models import JobInsert
from scout.parsers import detect_remote
from scout.scrapers.catalog_base import CatalogScraper, TargetCompany

log = logging.getLogger("scout.scrapers.lever")

_API_BASE = "https://api.lever.co/v0/postings/{board_id}"
_TIMEOUT = 15.0


class LeverScraper(CatalogScraper):
    source_prefix = "lever"

    def scrape_company(self, company: TargetCompany) -> list[JobInsert]:
        url = _API_BASE.format(board_id=company.board_id)
        try:
            resp = httpx.get(url, timeout=_TIMEOUT)
        except httpx.HTTPError:
            log.warning("HTTP error fetching %s board '%s'", company.name, company.board_id, exc_info=True)
            return []

        if resp.status_code == 404:
            log.warning("Lever board not found: %s (board_id=%s)", company.name, company.board_id)
            return []
        if resp.status_code != 200:
            log.warning("Lever API returned %d for %s", resp.status_code, company.name)
            return []

        postings = resp.json()
        if not isinstance(postings, list):
            log.warning("Unexpected Lever response format for %s", company.name)
            return []

        log.info("Lever %s: %d postings", company.name, len(postings))

        jobs: list[JobInsert] = []
        for posting in postings:
            job = self._parse_posting(posting, company)
            if job:
                jobs.append(job)

        return jobs

    def _parse_posting(self, posting: dict, company: TargetCompany) -> JobInsert | None:
        title = posting.get("text", "").strip()
        job_id = posting.get("id", "")
        if not title or not job_id:
            return None

        # Lever location is under categories.location
        categories = posting.get("categories", {})
        location_name = categories.get("location", "")

        hosting_url = posting.get("hostedUrl", "")

        # Lever provides descriptionPlain for text, description for HTML
        description = posting.get("descriptionPlain", "") or posting.get("description", "")

        remote = detect_remote(location_name, title)

        return JobInsert(
            source=f"lever:{company.board_id}",
            source_id=str(job_id),
            url=hosting_url,
            title=title,
            company=company.name,
            description=description,
            location=location_name or None,
            remote=remote,
            salary_min=None,
            salary_max=None,
            date_posted=None,
        )

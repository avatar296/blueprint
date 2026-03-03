"""RemoteOK aggregator scraper — fetches the global remote jobs feed (no browser needed)."""

import logging
from datetime import datetime, timezone

import httpx

from common.models import JobInsert
from scout.scrapers.aggregator_base import AggregatorScraper

log = logging.getLogger("scout.scrapers.remoteok")

_API_URL = "https://remoteok.com/api"
_TIMEOUT = 20.0


class RemoteOKScraper(AggregatorScraper):
    source = "remoteok"

    def scrape_all(self) -> list[JobInsert]:
        try:
            resp = httpx.get(
                _API_URL,
                timeout=_TIMEOUT,
                headers={"User-Agent": "Blueprint Scout/1.0"},
            )
        except httpx.HTTPError:
            log.warning("HTTP error fetching RemoteOK feed", exc_info=True)
            return []

        if resp.status_code != 200:
            log.warning("RemoteOK API returned %d", resp.status_code)
            return []

        data = resp.json()
        # First element is metadata/legal notice, skip it
        postings = data[1:] if isinstance(data, list) and len(data) > 1 else []
        log.info("RemoteOK: %d postings in feed", len(postings))

        jobs: list[JobInsert] = []
        for posting in postings:
            job = self._parse_posting(posting)
            if job:
                jobs.append(job)

        return jobs

    def _parse_posting(self, posting: dict) -> JobInsert | None:
        title = posting.get("position", "").strip()
        company = posting.get("company", "").strip()
        job_id = posting.get("id", "")
        if not title or not company or not job_id:
            return None

        url = posting.get("url", "")
        description = posting.get("description", "")
        location = posting.get("location", "Worldwide")
        salary_min = posting.get("salary_min")
        salary_max = posting.get("salary_max")

        # Parse epoch timestamp
        date_posted = None
        if epoch := posting.get("epoch"):
            try:
                date_posted = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
            except (ValueError, TypeError, OSError):
                pass

        # Coerce salary fields to int or None
        try:
            salary_min = int(salary_min) if salary_min else None
        except (ValueError, TypeError):
            salary_min = None
        try:
            salary_max = int(salary_max) if salary_max else None
        except (ValueError, TypeError):
            salary_max = None

        return JobInsert(
            source="remoteok",
            source_id=str(job_id),
            url=url,
            title=title,
            company=company,
            description=description,
            location=location,
            remote=True,
            salary_min=salary_min,
            salary_max=salary_max,
            date_posted=date_posted,
        )

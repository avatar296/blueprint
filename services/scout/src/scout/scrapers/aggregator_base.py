"""Aggregator scraper ABC — pulls a global feed from an aggregator API (no browser needed)."""

from abc import ABC, abstractmethod

from common.models import JobInsert


class AggregatorScraper(ABC):
    """Abstract base for aggregator scrapers that fetch a single global feed."""

    source: str  # e.g. "remoteok"

    @abstractmethod
    def scrape_all(self) -> list[JobInsert]:
        """Fetch all relevant postings from the aggregator's API."""

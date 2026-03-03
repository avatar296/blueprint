"""Catalog scraper ABC — iterates over target companies via ATS APIs (no browser needed)."""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from common.models import JobInsert

log = logging.getLogger("scout.scrapers.catalog_base")


@dataclass
class TargetCompany:
    """A company to monitor via its ATS career board."""

    name: str
    ats: str  # "greenhouse" or "lever"
    board_id: str


class CatalogScraper(ABC):
    """Abstract base for ATS API scrapers that enumerate jobs per company."""

    source_prefix: str  # e.g. "greenhouse" — source field becomes "{prefix}:{board_id}"

    @abstractmethod
    def scrape_company(self, company: TargetCompany) -> list[JobInsert]:
        """Fetch all job postings for a single company via its ATS API.

        Returns raw JobInsert dicts — caller is responsible for title filtering.
        """

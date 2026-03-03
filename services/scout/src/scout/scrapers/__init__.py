"""Scraper registry — maps source names to scraper classes by mode."""

from scout.scrapers.greenhouse import GreenhouseScraper
from scout.scrapers.lever import LeverScraper
from scout.scrapers.remoteok import RemoteOKScraper
from scout.scrapers.workday import WorkdayScraper

# ATS API scrapers: iterate over target companies (keyed by ATS name)
CATALOG_SCRAPERS: dict[str, type] = {
    "greenhouse": GreenhouseScraper,
    "lever": LeverScraper,
    "workday": WorkdayScraper,
}

# Aggregator API scrapers: single global feed each
AGGREGATOR_SCRAPERS: dict[str, type] = {
    "remoteok": RemoteOKScraper,
}

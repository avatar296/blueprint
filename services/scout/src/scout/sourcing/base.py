"""Base types for company sourcing providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class CompanyRecord:
    """Normalized company record from any sourcing provider."""

    name: str
    source: str  # 'sec_edgar', 'wikidata'
    source_id: str | None = None  # CIK, QID, etc.
    employee_count: int | None = None
    date_founded: str | None = None  # ISO date string (YYYY-MM-DD)
    state: str | None = None  # US state code
    city: str | None = None
    industry: str | None = None
    sic_code: str | None = None
    website: str | None = None
    ticker: str | None = None
    exchange: str | None = None
    filer_category: str | None = None
    total_assets: int | None = None
    naics_code: str | None = None
    description: str | None = None


class CompanySource(ABC):
    """Abstract base for company sourcing providers."""

    name: str  # short identifier for logging

    @abstractmethod
    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        """Fetch company records from the data source.

        Args:
            max_records: Maximum number of records to return (0 = unlimited).

        Returns a list of CompanyRecord objects.
        Implementations should handle their own rate limiting and retries.
        """

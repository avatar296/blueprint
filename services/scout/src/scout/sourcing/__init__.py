"""Company sourcing providers — populate the companies table from public data."""

from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.careeronestop import CareerOneStopSource
from scout.sourcing.sec_edgar import SecEdgarSource
from scout.sourcing.wikidata import WikidataSource

__all__ = [
    "CompanyRecord",
    "CompanySource",
    "SecEdgarSource",
    "WikidataSource",
    "CareerOneStopSource",
]

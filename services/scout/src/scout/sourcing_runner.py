"""Sourcing runner — orchestrates company data providers and upserts into companies table."""

import logging

from common.companies import get_company_count, upsert_company
from scout.discovery import normalize_company_name
from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.careeronestop import CareerOneStopSource
from scout.sourcing.sec_edgar import SecEdgarSource
from scout.sourcing.wikidata import WikidataSource

log = logging.getLogger("scout.sourcing_runner")


def _get_enabled_providers() -> list[CompanySource]:
    """Return the list of sourcing providers to run.

    SEC EDGAR and Wikidata always run. CareerOneStop only if credentials are set.
    """
    providers: list[CompanySource] = [
        SecEdgarSource(),
        WikidataSource(),
    ]

    cos = CareerOneStopSource()
    if cos.is_configured():
        providers.append(cos)
        log.info("CareerOneStop credentials found — will include in sourcing")
    else:
        log.info("CareerOneStop credentials not set — skipping")

    return providers


def _upsert_record(record: CompanyRecord) -> None:
    """Normalize and upsert a single CompanyRecord into the companies table."""
    normalized = normalize_company_name(record.name)
    if not normalized:
        return

    upsert_company(
        name=record.name,
        normalized_name=normalized,
        source=record.source,
        source_id=record.source_id,
        employee_count=record.employee_count,
        date_founded=record.date_founded,
        state=record.state,
        city=record.city,
        industry=record.industry,
        sic_code=record.sic_code,
        website=record.website,
    )


def run_sourcing() -> int:
    """Run all enabled sourcing providers and upsert results.

    Returns the total number of records upserted.
    """
    providers = _get_enabled_providers()
    log.info("Running %d sourcing providers", len(providers))

    count_before = get_company_count()
    total_fetched = 0

    for provider in providers:
        log.info("--- Sourcing: %s ---", provider.name)
        try:
            records = provider.fetch()
            total_fetched += len(records)
            log.info("%s: fetched %d records, upserting...", provider.name, len(records))

            for record in records:
                try:
                    _upsert_record(record)
                except Exception:
                    log.debug(
                        "Failed to upsert %s from %s",
                        record.name, record.source,
                        exc_info=True,
                    )

        except Exception:
            log.error("Provider %s failed", provider.name, exc_info=True)

    count_after = get_company_count()
    new_companies = count_after - count_before

    log.info(
        "Sourcing complete: %d records fetched, %d new companies (total: %d)",
        total_fetched, new_companies, count_after,
    )
    return total_fetched

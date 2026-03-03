"""Sourcing runner — orchestrates company data providers and upserts into companies table."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from common.companies import get_company_count, upsert_company
from scout.discovery import normalize_company_name
from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.colorado_sos import ColoradoSosSource
from scout.sourcing.fdic import FdicSource
from scout.sourcing.iowa_sos import IowaSosSource
from scout.sourcing.ncua import NcuaSource
from scout.sourcing.newyork_sos import NewYorkSosSource
from scout.sourcing.oregon_sos import OregonSosSource
from scout.sourcing.osha import OshaSource
from scout.sourcing.propublica import ProPublicaSource
from scout.sourcing.sba_ppp import SbaPppSource
from scout.sourcing.sec_edgar import SecEdgarSource
from scout.sourcing.texas_sos import TexasSosSource
from scout.sourcing.wikidata import WikidataSource

log = logging.getLogger("scout.sourcing_runner")


def _get_enabled_providers() -> list[CompanySource]:
    """Return the list of sourcing providers to run."""
    providers: list[CompanySource] = [
        SecEdgarSource(),
        WikidataSource(),
        ProPublicaSource(),
        ColoradoSosSource(),
        TexasSosSource(),
        NewYorkSosSource(),
        OregonSosSource(),
        IowaSosSource(),
        FdicSource(),
        NcuaSource(),
        SbaPppSource(),
        OshaSource(),
    ]
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
        ticker=record.ticker,
        exchange=record.exchange,
        filer_category=record.filer_category,
        total_assets=record.total_assets,
        naics_code=record.naics_code,
        description=record.description,
    )


def run_sourcing(source_batch_limit: int = 0) -> int:
    """Run all enabled sourcing providers and upsert results.

    Args:
        source_batch_limit: Max records per provider (0 = unlimited).

    Returns the total number of records upserted.
    """
    providers = _get_enabled_providers()
    log.info("Running %d sourcing providers (batch_limit=%s)", len(providers), source_batch_limit or "unlimited")

    count_before = get_company_count()
    total_fetched = 0

    def _fetch_provider(provider: CompanySource) -> tuple[str, list[CompanyRecord]]:
        log.info("--- Sourcing: %s ---", provider.name)
        records = provider.fetch(max_records=source_batch_limit)
        log.info("%s: fetched %d records", provider.name, len(records))
        return provider.name, records

    all_records: list[CompanyRecord] = []
    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {executor.submit(_fetch_provider, p): p for p in providers}
        for future in as_completed(futures):
            provider = futures[future]
            try:
                _name, records = future.result()
                total_fetched += len(records)
                all_records.extend(records)
            except Exception:
                log.error("Provider %s failed", provider.name, exc_info=True)

    # Sequential upsert after all fetches complete
    for record in all_records:
        try:
            _upsert_record(record)
        except Exception:
            log.debug(
                "Failed to upsert %s from %s",
                record.name, record.source,
                exc_info=True,
            )

    count_after = get_company_count()
    new_companies = count_after - count_before

    log.info(
        "Sourcing complete: %d records fetched, %d new companies (total: %d)",
        total_fetched, new_companies, count_after,
    )
    return total_fetched

"""Sourcing runner — orchestrates company data providers and upserts into companies table."""

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from common.companies import get_company_count, upsert_companies_batch
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


def _prepare_record(record: CompanyRecord) -> tuple | None:
    """Normalize a CompanyRecord into a parameter tuple for batch upsert.

    Returns None if the name normalizes to empty.
    """
    normalized = normalize_company_name(record.name)
    if not normalized:
        return None

    return (
        record.name,
        normalized,
        record.source,
        record.source_id,
        record.employee_count,
        record.date_founded,
        record.state,
        record.city,
        record.industry,
        record.sic_code,
        record.website,
        record.ticker,
        record.exchange,
        record.filer_category,
        record.total_assets,
        record.naics_code,
        record.description,
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
    total_upserted = 0

    def _fetch_provider(provider: CompanySource) -> tuple[str, list[CompanyRecord]]:
        log.info("--- Sourcing: %s ---", provider.name)
        records = provider.fetch(max_records=source_batch_limit)
        log.info("%s: fetched %d records", provider.name, len(records))
        return provider.name, records

    with ThreadPoolExecutor(max_workers=len(providers)) as executor:
        futures = {executor.submit(_fetch_provider, p): p for p in providers}
        for future in as_completed(futures):
            provider = futures[future]
            try:
                name, records = future.result()
                rows = [t for r in records if (t := _prepare_record(r)) is not None]
                upserted = upsert_companies_batch(rows)
                total_upserted += upserted
                log.info("%s: upserted %d rows", name, upserted)
            except Exception:
                log.error("Provider %s failed", provider.name, exc_info=True)

    count_after = get_company_count()
    new_companies = count_after - count_before

    log.info(
        "Sourcing complete: %d records upserted, %d new companies (total: %d)",
        total_upserted, new_companies, count_after,
    )
    return total_upserted

"""Sourcing runner — orchestrates company data providers and upserts into companies table."""

import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from common.companies import get_company_count, upsert_companies_batch
from common.sourcing_runs import (
    complete_run,
    create_run,
    fail_run,
    insert_provider_result,
)
from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.colorado_sos import ColoradoSosSource
from scout.sourcing.fdic import FdicSource
from scout.sourcing.iowa_sos import IowaSosSource
from scout.sourcing.ncua import NcuaSource
from scout.sourcing.newyork_sos import NewYorkSosSource
from scout.sourcing.oregon_sos import OregonSosSource
from scout.sourcing.propublica import ProPublicaSource
from scout.sourcing.sba_ppp import SbaPppSource
from scout.sourcing.sec_edgar import SecEdgarSource
from scout.sourcing.texas_sos import TexasSosSource
from scout.sourcing.wikidata import WikidataSource

log = logging.getLogger("scout.sourcing_runner")

_SUFFIXES = re.compile(
    r",?\s*\b(Inc\.?|Corp\.?|LLC|Ltd\.?|L\.?P\.?|Co\.?|Company"
    r"|Technologies|Technology|Group|Holdings|Solutions|Services"
    r"|Software|Labs|Laboratories|Systems|Enterprises?|International)\b\.?",
    re.IGNORECASE,
)


def normalize_company_name(name: str) -> str:
    """Lowercase and strip common corporate suffixes for dedup.

    >>> normalize_company_name("Palantir Technologies, Inc.")
    'palantir'
    >>> normalize_company_name("Shield AI")
    'shield ai'
    """
    cleaned = _SUFFIXES.sub("", name)
    cleaned = cleaned.strip(" ,.-")
    return cleaned.lower()


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

    run_id = create_run()
    count_before = get_company_count()
    total_upserted = 0

    def _fetch_provider(provider: CompanySource) -> tuple[str, list[CompanyRecord], float]:
        log.info("--- Sourcing: %s ---", provider.name)
        t0 = time.monotonic()
        records = provider.fetch(max_records=source_batch_limit)
        elapsed = time.monotonic() - t0
        log.info("%s: fetched %d records in %.1fs", provider.name, len(records), elapsed)
        return provider.name, records, elapsed

    try:
        with ThreadPoolExecutor(max_workers=len(providers)) as executor:
            futures = {executor.submit(_fetch_provider, p): p for p in providers}
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    name, records, elapsed = future.result()
                    rows = [t for r in records if (t := _prepare_record(r)) is not None]
                    upserted = upsert_companies_batch(rows)
                    total_upserted += upserted
                    log.info("%s: upserted %d rows", name, upserted)
                    insert_provider_result(
                        run_id, name, len(records), upserted, elapsed,
                    )
                except Exception:
                    log.error("Provider %s failed", provider.name, exc_info=True)
                    insert_provider_result(
                        run_id, provider.name, 0, 0, 0.0,
                        error_message=str(future.exception()),
                    )

        count_after = get_company_count()
        complete_run(run_id, count_before, count_after, total_upserted)

        new_companies = count_after - count_before
        log.info(
            "Sourcing complete: %d records upserted, %d new companies (total: %d)",
            total_upserted, new_companies, count_after,
        )
    except Exception as exc:
        fail_run(run_id, str(exc))
        raise

    return total_upserted

"""Scout service entrypoint — orchestrates config, scrapers, and DB inserts."""

import logging
import os
import signal
import sys
import time
from collections import defaultdict

from common.db import get_pool
from common.discovery import fetch_filtered_discoveries
from common.jobs import insert_job

from scout.config import load_config, ScoutConfig
from scout.discovery import run_discovery_phase
from scout.filters import is_fresh, is_relevant_title
from scout.scrapers import AGGREGATOR_SCRAPERS, CATALOG_SCRAPERS
from scout.scrapers.catalog_base import TargetCompany
from scout.sourcing_runner import run_sourcing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("scout")

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %d — shutting down gracefully", signum)
    _shutdown = True


def check_env() -> None:
    required = ["DATABASE_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def _insert_jobs(jobs, total_inserted: int) -> int:
    """Insert a list of JobInsert dicts into the DB. Returns updated total_inserted count."""
    for job in jobs:
        try:
            job_id = insert_job(job)
            if job_id:
                total_inserted += 1
                log.debug("Inserted: %s at %s [%s]", job["title"], job["company"], job_id)
        except Exception:
            log.warning("DB insert failed for %s at %s", job.get("title"), job.get("company"), exc_info=True)
    return total_inserted


def _run_catalog_phase(config: ScoutConfig) -> tuple[int, int]:
    """Phase 2: ATS API catalog scrapers — reads from DB-driven filtered discoveries."""
    # Fetch discoveries filtered by company metadata
    has_filters = any([
        config.min_employees, config.max_employees,
        config.founded_after, config.filter_states, config.filter_industries,
    ])

    if has_filters:
        discoveries = fetch_filtered_discoveries(
            min_employees=config.min_employees,
            max_employees=config.max_employees,
            founded_after=config.founded_after,
            states=config.filter_states or None,
            industries=config.filter_industries or None,
        )
    else:
        discoveries = fetch_filtered_discoveries()

    if not discoveries:
        log.info("No active ATS discoveries — skipping catalog phase")
        return 0, 0

    # Convert to TargetCompany objects for scraper interface compatibility
    target_companies = [
        TargetCompany(name=d["company_name"], ats=d["ats"], board_id=d["board_id"])
        for d in discoveries
    ]

    log.info("Catalog phase: %d companies from DB discoveries", len(target_companies))

    # Group companies by ATS platform
    by_ats: dict[str, list] = defaultdict(list)
    for company in target_companies:
        by_ats[company.ats].append(company)

    total_inserted = 0
    total_seen = 0

    for ats_name, companies in by_ats.items():
        if _shutdown:
            break

        scraper_cls = CATALOG_SCRAPERS.get(ats_name)
        if not scraper_cls:
            log.warning("No catalog scraper registered for ATS '%s'", ats_name)
            continue

        scraper = scraper_cls()
        log.info("--- Catalog source: %s (%d companies) ---", ats_name, len(companies))

        for company in companies:
            if _shutdown:
                break

            log.info("Fetching %s via %s (board: %s)", company.name, ats_name, company.board_id)
            try:
                raw_jobs = scraper.scrape_company(company)
            except Exception:
                log.warning("Catalog scrape failed for %s", company.name, exc_info=True)
                continue

            # Filter by title relevance and freshness before inserting
            jobs = [
                j for j in raw_jobs
                if is_relevant_title(j["title"], config.roles)
                and is_fresh(j.get("date_posted"), config.max_age_days)
            ]
            log.info(
                "%s: %d total postings, %d relevant after title/freshness filter",
                company.name, len(raw_jobs), len(jobs),
            )

            total_seen += len(raw_jobs)
            total_inserted = _insert_jobs(jobs, total_inserted)

    return total_seen, total_inserted


def _run_aggregator_phase(config: ScoutConfig) -> tuple[int, int]:
    """Phase 3: Aggregator API scrapers (RemoteOK)."""
    total_inserted = 0
    total_seen = 0

    for source_name, scraper_cls in AGGREGATOR_SCRAPERS.items():
        if _shutdown:
            break

        log.info("--- Aggregator source: %s ---", source_name)
        scraper = scraper_cls()

        try:
            raw_jobs = scraper.scrape_all()
        except Exception:
            log.warning("Aggregator scrape failed for %s", source_name, exc_info=True)
            continue

        # Filter by title relevance and freshness before inserting
        jobs = [
            j for j in raw_jobs
            if is_relevant_title(j["title"], config.roles)
            and is_fresh(j.get("date_posted"), config.max_age_days)
        ]
        log.info(
            "%s: %d total postings, %d relevant after title/freshness filter",
            source_name, len(raw_jobs), len(jobs),
        )

        total_seen += len(raw_jobs)
        total_inserted = _insert_jobs(jobs, total_inserted)

    return total_seen, total_inserted


def run_cycle(force_sourcing: bool = False) -> int:
    """Run one full scrape cycle across all sources. Returns total jobs inserted."""
    config = load_config()

    # Phase 0: Company sourcing (conditionally)
    if force_sourcing:
        log.info("=== Phase 0: Company sourcing ===")
        try:
            run_sourcing(source_batch_limit=config.source_batch_limit)
        except Exception:
            log.error("Sourcing phase failed", exc_info=True)

    # Phase 1: ATS auto-discovery (from companies table)
    log.info("=== Phase 1: ATS discovery ===")
    try:
        run_discovery_phase()
    except Exception:
        log.warning("Discovery phase failed — continuing with existing discoveries", exc_info=True)

    # Phase 2: ATS catalog scrapers (DB-driven)
    log.info("=== Phase 2: Catalog scrapers ===")
    catalog_seen, catalog_inserted = _run_catalog_phase(config)

    # Phase 3: Aggregator scrapers
    log.info("=== Phase 3: Aggregator scrapers ===")
    agg_seen, agg_inserted = _run_aggregator_phase(config)

    total_seen = catalog_seen + agg_seen
    total_inserted = catalog_inserted + agg_inserted

    log.info(
        "Cycle complete: %d seen, %d new — catalog=%d/%d, aggregator=%d/%d",
        total_seen, total_inserted,
        catalog_inserted, catalog_seen,
        agg_inserted, agg_seen,
    )
    return total_inserted


def main() -> None:
    check_env()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    interval = int(os.getenv("SCOUT_INTERVAL_MINUTES", "60")) * 60
    sourcing_interval = int(os.getenv("SCOUT_SOURCING_INTERVAL_HOURS", "168")) * 3600
    log.info(
        "Scout starting — cycle every %d min, sourcing every %d hours",
        interval // 60, sourcing_interval // 3600,
    )

    # Eagerly initialize the DB pool to fail fast on bad credentials
    get_pool()
    log.info("Database connection pool initialized")

    # Track when we last ran sourcing — force on first run
    last_sourcing = 0.0

    while not _shutdown:
        log.info("Scout cycle starting")

        # Determine if sourcing should run this cycle
        now = time.monotonic()
        force_sourcing = (now - last_sourcing) >= sourcing_interval
        if force_sourcing:
            last_sourcing = now

        try:
            run_cycle(force_sourcing=force_sourcing)
        except Exception:
            log.error("Cycle failed unexpectedly", exc_info=True)

        # Interruptible sleep — check shutdown flag every 5 seconds
        elapsed = 0
        while elapsed < interval and not _shutdown:
            time.sleep(5)
            elapsed += 5

    log.info("Scout shutdown complete")


if __name__ == "__main__":
    main()

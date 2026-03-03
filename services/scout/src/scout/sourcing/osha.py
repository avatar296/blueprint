"""OSHA Inspection Data — sourcing establishments with employee counts from DOL."""

import csv
import logging
import os
import tempfile

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource
from scout.sourcing.sba_ppp import _naics_to_industry

log = logging.getLogger("scout.sourcing.osha")

# The DOL migrated enforcedata.dol.gov to a React SPA (data.dol.gov) in 2025,
# breaking all legacy CSV download URLs.  The OSHA inspection CSV must now be
# supplied via SCOUT_OSHA_INSPECTION_URL env var.

_REQUIRED_COLUMNS = {"activity_nr", "estab_name", "site_state"}


class OshaSource(CompanySource):
    """Fetch establishments with employee counts from OSHA inspection data."""

    name = "osha"

    def __init__(self) -> None:
        self._url = os.environ.get("SCOUT_OSHA_INSPECTION_URL", "")

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        url = self._resolve_url()
        if not url:
            log.warning(
                "OSHA: no working download URL found. "
                "Set SCOUT_OSHA_INSPECTION_URL env var to the current inspection CSV URL. "
                "Check https://data.dol.gov/ or https://www.osha.gov/data for the latest link."
            )
            return []

        log.info("OSHA: downloading from %s", url)
        csv_path = self._download(url)
        if not csv_path:
            return []

        try:
            records = self._parse_and_dedup(csv_path, max_records)
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass

        log.info("OSHA: fetched %d unique establishments", len(records))
        return records

    def _resolve_url(self) -> str | None:
        """Return configured URL or None."""
        if self._url:
            return self._url
        return None

    def _download(self, url: str) -> str | None:
        """Stream download CSV to a temp file, return path or None on failure."""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False, mode="wb",
            ) as tmp:
                tmp_path = tmp.name
                with httpx.stream("GET", url, timeout=300.0, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        tmp.write(chunk)

            return tmp_path

        except httpx.HTTPError as exc:
            log.error("OSHA: download failed: %s", exc)
            return None

    def _parse_and_dedup(self, csv_path: str, max_records: int) -> list[CompanyRecord]:
        """Stream-parse CSV, dedup by estab_name+state, keep highest nr_in_estab."""
        best: dict[str, CompanyRecord] = {}

        with open(csv_path, encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)

            if reader.fieldnames is None:
                log.error("OSHA: CSV has no header row")
                return []

            available = set(reader.fieldnames)
            missing = _REQUIRED_COLUMNS - available
            if missing:
                log.error(
                    "OSHA: CSV missing required columns %s (available: %s)",
                    missing, sorted(available),
                )
                return []

            row_count = 0
            for row in reader:
                row_count += 1
                name_raw = (row.get("estab_name") or "").strip()
                state_raw = (row.get("site_state") or "").strip()
                if not name_raw:
                    continue

                dedup_key = name_raw.lower() + "|" + state_raw.lower()

                # Employee count
                emp_count = None
                emp_raw = (row.get("nr_in_estab") or "").strip()
                if emp_raw:
                    try:
                        emp_count = int(float(emp_raw))
                        if emp_count <= 0:
                            emp_count = None
                    except (ValueError, TypeError):
                        pass

                # Keep record with highest employee count
                if dedup_key in best:
                    existing_emp = best[dedup_key].employee_count or 0
                    new_emp = emp_count or 0
                    if new_emp <= existing_emp:
                        continue

                naics_raw = (row.get("naics_code") or "").strip()
                sic_raw = (row.get("sic_code") or "").strip()

                record = CompanyRecord(
                    name=name_raw.title(),
                    source="osha",
                    source_id=(row.get("activity_nr") or "").strip() or None,
                    city=((row.get("site_city") or "").strip().title()) or None,
                    state=(state_raw.upper()) or None,
                    employee_count=emp_count,
                    naics_code=naics_raw or None,
                    sic_code=sic_raw or None,
                    industry=_naics_to_industry(naics_raw),
                )
                best[dedup_key] = record

            log.info("OSHA: parsed %d rows → %d unique establishments", row_count, len(best))

        records = list(best.values())
        if max_records > 0:
            records = records[:max_records]
        return records

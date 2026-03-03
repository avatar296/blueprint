"""SBA PPP Loans — sourcing businesses from Paycheck Protection Program data ($150k+)."""

import csv
import logging
import os
import tempfile

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.sba_ppp")

_DEFAULT_URL = (
    "https://data.sba.gov/dataset/8aa276e2-6cab-4f86-aca4-a7dde42adf24/"
    "resource/c1275a03-c25c-488a-bd95-403c4b2fa036/"
    "download/public_150k_plus_240930.csv"
)

_REQUIRED_COLUMNS = {"LoanNumber", "BorrowerName", "BorrowerState"}

# 2-digit NAICS sector code → industry name
_NAICS_SECTOR: dict[str, str] = {
    "11": "Agriculture, Forestry, Fishing & Hunting",
    "21": "Mining, Quarrying & Oil/Gas Extraction",
    "22": "Utilities",
    "23": "Construction",
    "31": "Manufacturing",
    "32": "Manufacturing",
    "33": "Manufacturing",
    "42": "Wholesale Trade",
    "44": "Retail Trade",
    "45": "Retail Trade",
    "48": "Transportation & Warehousing",
    "49": "Transportation & Warehousing",
    "51": "Information",
    "52": "Finance & Insurance",
    "53": "Real Estate & Rental/Leasing",
    "54": "Professional, Scientific & Technical Services",
    "55": "Management of Companies & Enterprises",
    "56": "Administrative & Support Services",
    "61": "Educational Services",
    "62": "Health Care & Social Assistance",
    "71": "Arts, Entertainment & Recreation",
    "72": "Accommodation & Food Services",
    "81": "Other Services (except Public Administration)",
    "92": "Public Administration",
}


def _naics_to_industry(naics: str) -> str | None:
    """Map a NAICS code to its 2-digit sector industry name."""
    if not naics or len(naics) < 2:
        return None
    return _NAICS_SECTOR.get(naics[:2])


class SbaPppSource(CompanySource):
    """Fetch businesses from SBA PPP loan data ($150k+ file)."""

    name = "sba_ppp"

    def __init__(self) -> None:
        self._url = os.environ.get("SCOUT_SBA_PPP_URL", _DEFAULT_URL)

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        log.info("SBA PPP: downloading from %s", self._url)

        csv_path = self._download()
        if not csv_path:
            return []

        try:
            records = self._parse_and_dedup(csv_path, max_records)
        finally:
            try:
                os.unlink(csv_path)
            except OSError:
                pass

        log.info("SBA PPP: fetched %d unique businesses", len(records))
        return records

    def _download(self) -> str | None:
        """Download CSV to a temp file, return path or None on failure."""
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".csv", delete=False, mode="wb",
            ) as tmp:
                tmp_path = tmp.name
                with httpx.stream("GET", self._url, timeout=300.0, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                        tmp.write(chunk)

            return tmp_path

        except httpx.HTTPError as exc:
            log.error("SBA PPP: download failed: %s", exc)
            return None

    def _parse_and_dedup(self, csv_path: str, max_records: int) -> list[CompanyRecord]:
        """Stream-parse CSV, dedup by borrower name+state, keep highest JobsReported."""
        # dedup_key → CompanyRecord (keep record with highest employee_count)
        best: dict[str, CompanyRecord] = {}

        with open(csv_path, encoding="utf-8", errors="replace", newline="") as fh:
            reader = csv.DictReader(fh)

            if reader.fieldnames is None:
                log.error("SBA PPP: CSV has no header row")
                return []

            available = set(reader.fieldnames)
            missing = _REQUIRED_COLUMNS - available
            if missing:
                log.error(
                    "SBA PPP: CSV missing required columns %s (available: %s)",
                    missing, sorted(available),
                )
                return []

            row_count = 0
            for row in reader:
                row_count += 1
                name_raw = (row.get("BorrowerName") or "").strip()
                state_raw = (row.get("BorrowerState") or "").strip()
                if not name_raw:
                    continue

                # Dedup key: lowercase name + state
                dedup_key = name_raw.lower() + "|" + state_raw.lower()

                # Employee count
                emp_count = None
                jobs_raw = (row.get("JobsReported") or "").strip()
                if jobs_raw:
                    try:
                        emp_count = int(float(jobs_raw))
                        if emp_count < 0:
                            emp_count = None
                    except (ValueError, TypeError):
                        pass

                # If we already have this business, keep the one with more employees
                if dedup_key in best:
                    existing = best[dedup_key]
                    existing_emp = existing.employee_count or 0
                    new_emp = emp_count or 0
                    if new_emp <= existing_emp:
                        continue

                naics_raw = (row.get("NAICSCode") or "").strip()

                record = CompanyRecord(
                    name=name_raw.title(),
                    source="sba_ppp",
                    source_id=(row.get("LoanNumber") or "").strip() or None,
                    city=((row.get("BorrowerCity") or "").strip().title()) or None,
                    state=(state_raw.upper()) or None,
                    employee_count=emp_count,
                    naics_code=naics_raw or None,
                    industry=_naics_to_industry(naics_raw),
                    filer_category=((row.get("BusinessType") or "").strip()) or None,
                )
                best[dedup_key] = record

            log.info("SBA PPP: parsed %d rows → %d unique businesses", row_count, len(best))

        records = list(best.values())
        if max_records > 0:
            records = records[:max_records]
        return records

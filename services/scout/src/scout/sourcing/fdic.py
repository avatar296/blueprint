"""FDIC BankFind — sourcing FDIC-insured banking institutions."""

import logging
import time

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.fdic")

_API_URL = "https://api.fdic.gov/banks/institutions"
_PAGE_SIZE = 10_000
_RATE_DELAY = 0.5  # seconds between pages


class FdicSource(CompanySource):
    """Fetch FDIC-insured banks from the BankFind REST API."""

    name = "fdic"

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        records: list[CompanyRecord] = []
        seen: set[str] = set()
        offset = 0

        while True:
            if max_records > 0 and len(records) >= max_records:
                break

            params: dict[str, str | int] = {
                "filters": "ACTIVE:1",
                "fields": "CERT,NAME,CITY,STALP,ASSET,ESTYMD,SPECGRPN",
                "limit": _PAGE_SIZE,
                "offset": offset,
            }

            try:
                if offset > 0:
                    time.sleep(_RATE_DELAY)

                resp = httpx.get(_API_URL, params=params, timeout=30.0)

                if resp.status_code != 200:
                    log.warning("FDIC API returned %d at offset %d", resp.status_code, offset)
                    break

                body = resp.json()
                rows = body.get("data", [])
                if not rows:
                    break

                for row in rows:
                    if max_records > 0 and len(records) >= max_records:
                        break

                    d = row.get("data", {})
                    cert = str(d.get("CERT") or d.get("ID") or "").strip()
                    name = (d.get("NAME") or "").strip()
                    if not cert or not name or cert in seen:
                        continue
                    seen.add(cert)

                    # Total assets: API reports in thousands
                    total_assets = None
                    raw_assets = d.get("ASSET")
                    if raw_assets is not None:
                        try:
                            total_assets = int(raw_assets) * 1000
                        except (TypeError, ValueError):
                            pass

                    # Date founded: MM/DD/YYYY → YYYY-MM-DD
                    date_founded = None
                    raw_date = (d.get("ESTYMD") or "").strip()
                    if raw_date:
                        date_founded = _parse_date(raw_date)

                    records.append(CompanyRecord(
                        name=name.title(),
                        source="fdic",
                        source_id=cert,
                        city=((d.get("CITY") or "").strip().title()) or None,
                        state=((d.get("STALP") or "").strip().upper()) or None,
                        total_assets=total_assets,
                        date_founded=date_founded,
                        filer_category=((d.get("SPECGRPN") or "").strip()) or None,
                        industry="Banking & Financial Services",
                    ))

                if len(rows) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE

            except (httpx.HTTPError, ValueError) as exc:
                log.warning("FDIC API error at offset %d: %s", offset, exc)
                break

        log.info("FDIC: fetched %d banks", len(records))
        return records


def _parse_date(raw: str) -> str | None:
    """Convert MM/DD/YYYY to YYYY-MM-DD, return None on failure."""
    parts = raw.split("/")
    if len(parts) != 3:
        return None
    try:
        month, day, year = parts
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except (ValueError, IndexError):
        return None

"""Shared base class for Socrata SODA API-based state business registries."""

import logging
import time
from dataclasses import dataclass, field

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.socrata")

_PAGE_SIZE = 50_000
_RATE_LIMIT_DELAY = 1.0  # seconds between pages
_BACKOFF_429 = 30.0  # seconds on rate-limit response


@dataclass
class SocrataStateConfig:
    """Field mapping + filter config for a single state's Socrata dataset."""

    endpoint: str  # full SODA API URL
    source_name: str  # e.g. "colorado_sos"
    id_field: str  # "entityid" / "taxpayer_number"
    name_field: str  # "entityname" / "taxpayer_name"
    city_field: str  # "principalcity" / "taxpayer_city"
    state_field: str  # "principalstate" / "taxpayer_state"
    date_field: str  # "entityformdate" / "sos_charter_date"
    type_field: str  # "entitytype" / "taxpayer_organizational_type"
    where_clause: str  # SoQL $where filter
    type_labels: dict[str, str] = field(default_factory=dict)


class SocrataBusinessSource(CompanySource):
    """Fetch companies from a Socrata SODA API (state business registry)."""

    def __init__(self, config: SocrataStateConfig) -> None:
        self._config = config
        self.name = config.source_name

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        records: list[CompanyRecord] = []
        seen_ids: set[str] = set()
        offset = 0
        cfg = self._config

        select_fields = ",".join([
            cfg.id_field, cfg.name_field, cfg.city_field,
            cfg.state_field, cfg.date_field, cfg.type_field,
        ])

        while True:
            if max_records > 0 and len(records) >= max_records:
                break

            params: dict[str, str | int] = {
                "$select": select_fields,
                "$where": cfg.where_clause,
                "$order": cfg.id_field,
                "$limit": _PAGE_SIZE,
                "$offset": offset,
            }

            try:
                time.sleep(_RATE_LIMIT_DELAY)
                resp = httpx.get(cfg.endpoint, params=params, timeout=60.0)

                if resp.status_code == 429:
                    log.warning("%s: rate limited, backing off %.0fs", cfg.source_name, _BACKOFF_429)
                    time.sleep(_BACKOFF_429)
                    continue

                if resp.status_code != 200:
                    log.warning("%s: HTTP %d at offset %d", cfg.source_name, resp.status_code, offset)
                    break

                rows = resp.json()
                if not rows:
                    break

                for row in rows:
                    if max_records > 0 and len(records) >= max_records:
                        break

                    source_id = str(row.get(cfg.id_field, "")).strip()
                    name = row.get(cfg.name_field, "")
                    if not source_id or not name or source_id in seen_ids:
                        continue

                    seen_ids.add(source_id)

                    city_raw = row.get(cfg.city_field) or None
                    state_raw = row.get(cfg.state_field) or None
                    date_raw = row.get(cfg.date_field) or None
                    type_raw = row.get(cfg.type_field) or None

                    type_label = cfg.type_labels.get(type_raw, type_raw) if type_raw else None

                    records.append(CompanyRecord(
                        name=name.strip().title(),
                        source=cfg.source_name,
                        source_id=source_id,
                        city=city_raw.strip().title() if city_raw else None,
                        state=state_raw.strip().upper() if state_raw else None,
                        date_founded=date_raw[:10] if date_raw else None,
                        filer_category=type_label,
                    ))

                log.info(
                    "%s: fetched page at offset %d (%d rows, %d total)",
                    cfg.source_name, offset, len(rows), len(records),
                )

                if len(rows) < _PAGE_SIZE:
                    break

                offset += _PAGE_SIZE

            except (httpx.HTTPError, ValueError) as exc:
                log.warning("%s: API error at offset %d: %s", cfg.source_name, offset, exc)
                break

        log.info("%s: fetched %d companies total", cfg.source_name, len(records))
        return records

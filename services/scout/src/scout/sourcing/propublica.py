"""ProPublica Nonprofit Explorer — sourcing US nonprofits (hospitals, universities, labs)."""

import logging
import time

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.propublica")

_SEARCH_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json"
_PAGE_SIZE = 25  # API-fixed page size
_RATE_LIMIT_DELAY = 0.5  # 2 requests/sec

# US states + DC for iteration
_US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
    "DC",
]

# Top-level NTEE code → industry mapping
_NTEE_INDUSTRY: dict[str, str] = {
    "A": "Arts, Culture & Humanities",
    "B": "Education",
    "C": "Environment",
    "D": "Animal-Related",
    "E": "Health Care",
    "F": "Mental Health & Crisis Intervention",
    "G": "Diseases, Disorders & Medical Disciplines",
    "H": "Medical Research",
    "I": "Crime & Legal-Related",
    "J": "Employment",
    "K": "Food, Agriculture & Nutrition",
    "L": "Housing & Shelter",
    "M": "Public Safety, Disaster Preparedness & Relief",
    "N": "Recreation & Sports",
    "O": "Youth Development",
    "P": "Human Services",
    "Q": "International, Foreign Affairs & National Security",
    "R": "Civil Rights, Social Action & Advocacy",
    "S": "Community Improvement & Capacity Building",
    "T": "Philanthropy, Voluntarism & Grantmaking",
    "U": "Science & Technology",
    "V": "Social Science",
    "W": "Public & Societal Benefit",
    "X": "Religion-Related",
    "Y": "Mutual & Membership Benefit",
    "Z": "Unknown",
}


def _ntee_to_industry(ntee_code: str | None) -> str | None:
    """Map an NTEE code (e.g. 'E32') to its top-level industry category."""
    if not ntee_code:
        return None
    prefix = ntee_code[0].upper()
    return _NTEE_INDUSTRY.get(prefix)


class ProPublicaSource(CompanySource):
    """Fetch US nonprofits from ProPublica Nonprofit Explorer API."""

    name = "propublica"

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        records: list[CompanyRecord] = []
        seen_eins: set[str] = set()

        for state in _US_STATES:
            if max_records > 0 and len(records) >= max_records:
                break

            state_records = self._fetch_state(state, seen_eins, max_records - len(records) if max_records > 0 else 0)
            records.extend(state_records)
            log.info("ProPublica %s: %d orgs (total: %d)", state, len(state_records), len(records))

        log.info("ProPublica: fetched %d nonprofits across %d states", len(records), len(_US_STATES))
        return records

    def _fetch_state(self, state: str, seen_eins: set[str], remaining: int) -> list[CompanyRecord]:
        """Paginate through all nonprofits in a given state."""
        records: list[CompanyRecord] = []
        page = 0

        while True:
            if remaining > 0 and len(records) >= remaining:
                break

            params: dict[str, str | int] = {
                "state[id]": state,
                "page": page,
            }

            try:
                time.sleep(_RATE_LIMIT_DELAY)
                resp = httpx.get(_SEARCH_URL, params=params, timeout=30.0)

                if resp.status_code == 429:
                    log.warning("ProPublica rate limited, backing off 10s")
                    time.sleep(10)
                    continue

                if resp.status_code != 200:
                    log.debug("ProPublica returned %d for %s page %d", resp.status_code, state, page)
                    break

                data = resp.json()
                orgs = data.get("organizations", [])
                if not orgs:
                    break

                for org in orgs:
                    if remaining > 0 and len(records) >= remaining:
                        break

                    ein = str(org.get("ein", ""))
                    name = org.get("name", "")
                    if not ein or not name or ein in seen_eins:
                        continue

                    seen_eins.add(ein)

                    ntee_code = org.get("ntee_code") or None
                    city = org.get("city") or None
                    org_state = org.get("state") or state

                    total_assets = None
                    raw_assets = org.get("asset_amount")
                    if raw_assets is not None:
                        try:
                            total_assets = int(raw_assets)
                        except (TypeError, ValueError):
                            pass

                    records.append(CompanyRecord(
                        name=name.strip().title(),
                        source="propublica",
                        source_id=ein,
                        state=org_state,
                        city=city.strip().title() if city else None,
                        industry=_ntee_to_industry(ntee_code),
                        naics_code=ntee_code,
                        total_assets=total_assets,
                    ))

                # If fewer results than page size, we've hit the last page
                if len(orgs) < _PAGE_SIZE:
                    break

                page += 1

            except (httpx.HTTPError, ValueError) as exc:
                log.warning("ProPublica API error for %s page %d: %s", state, page, exc)
                break

        return records

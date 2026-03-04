"""ProPublica Nonprofit Explorer — sourcing US nonprofits (hospitals, universities, labs)."""

import asyncio
import logging

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.propublica")

_SEARCH_URL = "https://projects.propublica.org/nonprofits/api/v2/search.json"
_PAGE_SIZE = 25  # API-fixed page size
_MAX_CONCURRENT = 5  # parallel requests
_RETRY_BACKOFF = 30  # seconds on 429
_MAX_RETRIES = 3  # give up after this many 429s per page
_PAGE_DELAY = 0.5  # seconds between pages per state

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


def _parse_org(org: dict, state: str) -> CompanyRecord | None:
    """Parse a single ProPublica org dict into a CompanyRecord."""
    ein = str(org.get("ein", ""))
    name = org.get("name", "")
    if not ein or not name:
        return None

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

    return CompanyRecord(
        name=name.strip().title(),
        source="propublica",
        source_id=ein,
        state=org_state,
        city=city.strip().title() if city else None,
        industry=_ntee_to_industry(ntee_code),
        naics_code=ntee_code,
        total_assets=total_assets,
    )


async def _fetch_state(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    state: str,
    seen_eins: set[str],
    max_records: int,
) -> list[CompanyRecord]:
    """Paginate through all nonprofits in a given state."""
    records: list[CompanyRecord] = []
    page = 0
    retries = 0

    while True:
        if max_records > 0 and len(records) >= max_records:
            break

        params: dict[str, str | int] = {
            "state[id]": state,
            "page": page,
        }

        async with semaphore:
            try:
                resp = await client.get(_SEARCH_URL, params=params)
            except httpx.HTTPError as exc:
                log.warning("ProPublica HTTP error for %s page %d: %s", state, page, exc)
                break

        if resp.status_code == 429:
            retries += 1
            if retries > _MAX_RETRIES:
                log.warning("ProPublica %s: gave up after %d rate limits", state, retries)
                break
            log.warning("ProPublica rate limited on %s, backing off %ds", state, _RETRY_BACKOFF)
            await asyncio.sleep(_RETRY_BACKOFF)
            continue

        retries = 0  # reset on success

        if resp.status_code != 200:
            log.debug("ProPublica returned %d for %s page %d", resp.status_code, state, page)
            break

        try:
            data = resp.json()
        except ValueError:
            log.warning("ProPublica invalid JSON for %s page %d", state, page)
            break

        orgs = data.get("organizations", [])
        if not orgs:
            break

        for org in orgs:
            if max_records > 0 and len(records) >= max_records:
                break

            ein = str(org.get("ein", ""))
            if not ein or ein in seen_eins:
                continue
            seen_eins.add(ein)

            record = _parse_org(org, state)
            if record:
                records.append(record)

        if len(orgs) < _PAGE_SIZE:
            break

        page += 1
        await asyncio.sleep(_PAGE_DELAY)

    log.info("ProPublica %s: %d orgs", state, len(records))
    return records


async def _fetch_all(max_records: int) -> list[CompanyRecord]:
    """Fetch states sequentially to respect ProPublica rate limits."""
    seen_eins: set[str] = set()
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)
    records: list[CompanyRecord] = []

    async with httpx.AsyncClient(timeout=30.0) as client:
        for state in _US_STATES:
            if max_records > 0 and len(records) >= max_records:
                break
            state_records = await _fetch_state(
                client, semaphore, state, seen_eins, max_records,
            )
            records.extend(state_records)

    if max_records > 0:
        records = records[:max_records]

    log.info("ProPublica: fetched %d nonprofits across %d states", len(records), len(_US_STATES))
    return records


class ProPublicaSource(CompanySource):
    """Fetch US nonprofits from ProPublica Nonprofit Explorer API."""

    name = "propublica"

    def fetch(self, max_records: int = 0) -> list[CompanyRecord]:
        return asyncio.run(_fetch_all(max_records))

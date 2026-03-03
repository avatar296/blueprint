"""CareerOneStop company sourcing — top employers by state (optional, requires free API creds)."""

import logging
import os
import time

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.careeronestop")

_API_BASE = "https://api.careeronestop.org/v1/employer"
_REQUEST_DELAY = 0.2  # conservative rate limit

_US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]


class CareerOneStopSource(CompanySource):
    """Fetch top employers per US state from CareerOneStop API."""

    name = "careeronestop"

    def __init__(self) -> None:
        self._user_id = os.environ.get("CAREERONESTOP_USER_ID", "")
        self._api_token = os.environ.get("CAREERONESTOP_API_TOKEN", "")

    def is_configured(self) -> bool:
        return bool(self._user_id and self._api_token)

    def fetch(self) -> list[CompanyRecord]:
        if not self.is_configured():
            log.info("CareerOneStop credentials not set — skipping")
            return []

        records: list[CompanyRecord] = []
        seen_names: set[str] = set()

        for state in _US_STATES:
            state_records = self._fetch_state(state, seen_names)
            records.extend(state_records)
            time.sleep(_REQUEST_DELAY)

        log.info("CareerOneStop: fetched %d unique companies across all states", len(records))
        return records

    def _fetch_state(self, state: str, seen_names: set[str]) -> list[CompanyRecord]:
        """Fetch top employers for a single state."""
        url = f"{_API_BASE}/{self._user_id}/{state}/0/0/0/150"

        try:
            resp = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
            if resp.status_code != 200:
                log.debug("CareerOneStop returned %d for state %s", resp.status_code, state)
                return []

            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("CareerOneStop error for state %s: %s", state, exc)
            return []

        employers = data.get("EmployerList", [])
        records: list[CompanyRecord] = []

        for emp in employers:
            name = emp.get("EmployerName", "").strip()
            if not name:
                continue

            # Deduplicate across states — keep first occurrence
            name_lower = name.lower()
            if name_lower in seen_names:
                continue
            seen_names.add(name_lower)

            employee_count = None
            emp_count_raw = emp.get("NumberOfEmployees")
            if emp_count_raw:
                try:
                    employee_count = int(str(emp_count_raw).replace(",", ""))
                except (ValueError, TypeError):
                    pass

            records.append(CompanyRecord(
                name=name,
                source="careeronestop",
                state=state,
                employee_count=employee_count,
            ))

        log.debug("CareerOneStop: %d employers for %s", len(records), state)
        return records

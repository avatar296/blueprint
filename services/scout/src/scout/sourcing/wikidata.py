"""Wikidata SPARQL company sourcing — employee count, inception, HQ location, website, industry."""

import logging

import httpx

from scout.sourcing.base import CompanyRecord, CompanySource

log = logging.getLogger("scout.sourcing.wikidata")

_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"

# SPARQL query: US companies with employee count, optional inception/HQ/website/industry
_SPARQL_QUERY = """
SELECT ?company ?companyLabel ?employees ?inception ?hqCityLabel ?hqStateLabel
       ?website ?industryLabel ?wikidataId
WHERE {
  ?company wdt:P31/wdt:P279* wd:Q4830453 .   # instance of business enterprise (or subclass)
  ?company wdt:P17 wd:Q30 .                    # country: United States
  ?company wdt:P1128 ?employees .              # number of employees

  OPTIONAL { ?company wdt:P571 ?inception . }
  OPTIONAL {
    ?company wdt:P159 ?hqCity .
    ?hqCity wdt:P131* ?hqState .
    ?hqState wdt:P31 wd:Q35657 .               # state of the US
  }
  OPTIONAL { ?company wdt:P856 ?website . }
  OPTIONAL { ?company wdt:P452 ?industry . }

  BIND(REPLACE(STR(?company), "http://www.wikidata.org/entity/", "") AS ?wikidataId)

  SERVICE wikibase:label { bd:serviceParam wikibase:language "en" . }
}
"""

# Wikidata state labels → US state codes
_STATE_LABEL_MAP: dict[str, str] = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "Florida": "FL", "Georgia": "GA", "Hawaii": "HI", "Idaho": "ID",
    "Illinois": "IL", "Indiana": "IN", "Iowa": "IA", "Kansas": "KS",
    "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME", "Maryland": "MD",
    "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN", "Mississippi": "MS",
    "Missouri": "MO", "Montana": "MT", "Nebraska": "NE", "Nevada": "NV",
    "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM", "New York": "NY",
    "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH", "Oklahoma": "OK",
    "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI", "South Carolina": "SC",
    "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX", "Utah": "UT",
    "Vermont": "VT", "Virginia": "VA", "Washington": "WA", "West Virginia": "WV",
    "Wisconsin": "WI", "Wyoming": "WY", "District of Columbia": "DC",
}


class WikidataSource(CompanySource):
    """Fetch US companies from Wikidata via SPARQL."""

    name = "wikidata"

    def fetch(self) -> list[CompanyRecord]:
        try:
            resp = httpx.get(
                _SPARQL_ENDPOINT,
                params={"query": _SPARQL_QUERY, "format": "json"},
                headers={"User-Agent": "Blueprint/1.0 (job-search-tool)"},
                timeout=120.0,
            )
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.error("Wikidata SPARQL query failed: %s", exc)
            return []

        bindings = data.get("results", {}).get("bindings", [])
        log.info("Wikidata: received %d result bindings", len(bindings))

        # Deduplicate by QID — take the first (often highest employee count) binding
        seen_qids: set[str] = set()
        records: list[CompanyRecord] = []

        for binding in bindings:
            qid = _val(binding, "wikidataId")
            if not qid or qid in seen_qids:
                continue
            seen_qids.add(qid)

            name = _val(binding, "companyLabel")
            if not name:
                continue

            employees_str = _val(binding, "employees")
            employees = int(float(employees_str)) if employees_str else None

            inception_str = _val(binding, "inception")
            date_founded = None
            if inception_str:
                # Wikidata returns ISO datetime, take just the date part
                date_founded = inception_str[:10]

            city = _val(binding, "hqCityLabel")
            state_label = _val(binding, "hqStateLabel")
            state = _STATE_LABEL_MAP.get(state_label, "") if state_label else None

            website = _val(binding, "website")
            industry = _val(binding, "industryLabel")

            records.append(CompanyRecord(
                name=name,
                source="wikidata",
                source_id=qid,
                employee_count=employees,
                date_founded=date_founded,
                state=state if state else None,
                city=city,
                industry=industry,
                website=website,
            ))

        log.info("Wikidata: %d unique companies after dedup", len(records))
        return records


def _val(binding: dict, key: str) -> str | None:
    """Extract string value from a SPARQL binding, or None."""
    entry = binding.get(key)
    if entry and "value" in entry:
        return entry["value"]
    return None

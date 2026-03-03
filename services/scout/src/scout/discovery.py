"""ATS auto-discovery — probe Greenhouse/Lever boards for companies from the sourcing pipeline."""

import asyncio
import logging
import os
import re
from uuid import UUID

import httpx

from common.companies import (
    get_unprobed_companies as get_unprobed_sourced_companies,
    mark_probed,
)
from common.discovery import (
    fetch_active_discoveries,
    insert_discovery,
)

log = logging.getLogger("scout.discovery")

_SUFFIXES = re.compile(
    r",?\s*\b(Inc\.?|Corp\.?|LLC|Ltd\.?|L\.?P\.?|Co\.?|Company"
    r"|Technologies|Technology|Group|Holdings|Solutions|Services"
    r"|Software|Labs|Laboratories|Systems|Enterprises?|International)\b\.?",
    re.IGNORECASE,
)

_GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
_LEVER_API = "https://api.lever.co/v0/postings/{slug}"

_PROBE_TIMEOUT = 10.0
_PROBE_DELAY = 0.5


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


def generate_slugs(name: str) -> list[str]:
    """Generate candidate ATS board slugs from a company name.

    >>> generate_slugs("Shield AI")
    ['shieldai', 'shield-ai', 'shield']
    >>> generate_slugs("Palantir Technologies")
    ['palantirtechnologies', 'palantir-technologies', 'palantir']
    """
    # Strip suffixes first, then work with the cleaned name
    cleaned = _SUFFIXES.sub("", name).strip(" ,.-")
    words = cleaned.split()
    if not words:
        return []

    slugs: list[str] = []

    # Full name variants
    full_no_spaces = "".join(words).lower()
    full_hyphenated = "-".join(words).lower()
    first_word = words[0].lower()

    slugs.append(full_no_spaces)
    if full_hyphenated != full_no_spaces:
        slugs.append(full_hyphenated)
    if first_word != full_no_spaces:
        slugs.append(first_word)

    return slugs


async def _probe_greenhouse(client: httpx.AsyncClient, slug: str) -> bool:
    """Check if a Greenhouse board exists for the given slug."""
    try:
        resp = await client.get(_GREENHOUSE_API.format(slug=slug))
        if resp.status_code == 200:
            data = resp.json()
            return "jobs" in data
    except (httpx.HTTPError, ValueError):
        pass
    return False


async def _probe_lever(client: httpx.AsyncClient, slug: str) -> bool:
    """Check if a Lever board exists for the given slug."""
    try:
        resp = await client.get(_LEVER_API.format(slug=slug))
        if resp.status_code == 200:
            data = resp.json()
            return isinstance(data, list)
    except (httpx.HTTPError, ValueError):
        pass
    return False


async def probe_company(
    name: str,
    client: httpx.AsyncClient,
    existing_board_ids: set[str],
) -> list[tuple[str, str]]:
    """Probe Greenhouse and Lever for a company. Returns list of (ats, board_id) hits."""
    slugs = generate_slugs(name)
    hits: list[tuple[str, str]] = []

    for slug in slugs:
        if slug in existing_board_ids:
            continue

        # Try Greenhouse
        if await _probe_greenhouse(client, slug):
            log.info("Discovered Greenhouse board: %s -> %s", name, slug)
            hits.append(("greenhouse", slug))
            return hits  # stop on first hit

        await asyncio.sleep(_PROBE_DELAY)

        # Try Lever
        if await _probe_lever(client, slug):
            log.info("Discovered Lever board: %s -> %s", name, slug)
            hits.append(("lever", slug))
            return hits  # stop on first hit

        await asyncio.sleep(_PROBE_DELAY)

    return hits


async def _run_discovery_async() -> None:
    """Async core of discovery phase — probe companies from the companies table."""
    max_probes = int(os.getenv("SCOUT_MAX_DISCOVERY_PROBES", "10"))

    # Gather existing board IDs to avoid duplicate probes
    existing_discoveries = fetch_active_discoveries()
    existing_board_ids = {d["board_id"] for d in existing_discoveries}

    # Collect probing candidates from sourced companies
    candidates: list[_ProbeCandidate] = []

    sourced = get_unprobed_sourced_companies(limit=max_probes * 2)
    for row in sourced:
        candidates.append(_ProbeCandidate(
            name=row["name"],
            normalized=row["normalized_name"],
            company_id=row["id"],
        ))

    candidates = candidates[:max_probes]

    if not candidates:
        log.info("No new companies to probe")
        return

    log.info("Probing %d companies for Greenhouse/Lever boards", len(candidates))

    async with httpx.AsyncClient(timeout=_PROBE_TIMEOUT) as client:
        for candidate in candidates:
            hits = await probe_company(candidate.name, client, existing_board_ids)
            if hits:
                for ats, board_id in hits:
                    insert_discovery(
                        candidate.name, candidate.normalized, ats, board_id,
                        company_id=candidate.company_id,
                    )
            else:
                # Negative cache — don't re-probe this company
                insert_discovery(
                    candidate.name, candidate.normalized, None, None,
                    company_id=candidate.company_id,
                )
                log.debug("No ATS board found for %s", candidate.name)

            # Mark sourced companies as probed regardless of result
            mark_probed(candidate.company_id)


class _ProbeCandidate:
    """A company to probe for ATS boards."""

    __slots__ = ("name", "normalized", "company_id")

    def __init__(self, name: str, normalized: str, company_id: UUID) -> None:
        self.name = name
        self.normalized = normalized
        self.company_id = company_id


def run_discovery_phase() -> None:
    """Run ATS auto-discovery — probe sourced companies for ATS boards."""
    asyncio.run(_run_discovery_async())

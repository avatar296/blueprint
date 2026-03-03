"""Filters — title relevance and freshness pre-screening before DB insert."""

import re
from datetime import datetime, timezone

# Seniority markers that indicate a senior-level role
_SENIORITY_PATTERNS = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|director|head|vp|chief|distinguished|fellow)\b",
    re.IGNORECASE,
)

# Titles to exclude regardless of other signals
_EXCLUDE_PATTERNS = re.compile(
    r"\b(intern|internship|junior|jr\.?|associate|entry[\s-]?level|new[\s-]?grad|co-?op)\b",
    re.IGNORECASE,
)


def is_relevant_title(title: str, roles: list[str]) -> bool:
    """Return True if the job title is likely relevant to the target roles.

    Deliberately permissive — the Evaluator LLM handles fine-grained scoring later.

    Args:
        title: Job title string (e.g. "Principal Software Architect").
        roles: Target role keywords from config (e.g. ["Architect", "Engineer", "Data Scientist"]).
    """
    if not title:
        return False

    # Reject obvious junior/entry-level roles
    if _EXCLUDE_PATTERNS.search(title):
        return False

    # Check if title contains any target role keyword (case-insensitive)
    title_lower = title.lower()
    has_role_match = any(role.lower() in title_lower for role in roles)

    if not has_role_match:
        return False

    # Require a seniority marker
    if _SENIORITY_PATTERNS.search(title):
        return True

    # Allow through if the role keyword itself implies seniority (e.g. "Architect", "Director")
    seniority_roles = {"architect", "principal", "director", "head", "chief", "fellow", "distinguished"}
    if any(role.lower() in seniority_roles for role in roles if role.lower() in title_lower):
        return True

    return False


def is_fresh(date_posted: datetime | None, max_age_days: int = 30) -> bool:
    """Return True if the posting is recent enough to keep.

    Args:
        date_posted: Parsed posting date (None means unknown — always passes).
        max_age_days: Maximum age in days before a posting is considered stale.
    """
    if date_posted is None:
        return True

    now = datetime.now(timezone.utc)
    # Handle naive datetimes by assuming UTC
    if date_posted.tzinfo is None:
        date_posted = date_posted.replace(tzinfo=timezone.utc)

    age = now - date_posted
    return age.days <= max_age_days

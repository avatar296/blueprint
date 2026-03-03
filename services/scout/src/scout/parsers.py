"""Parsing utilities for salary, remote detection, and relative dates."""

import re
from datetime import datetime, timedelta, timezone


def parse_salary(text: str | None) -> tuple[int | None, int | None]:
    """Extract salary_min and salary_max from a salary string.

    Handles formats like:
        "$120,000 - $150,000/yr"
        "$80K-$100K"
        "$150,000/yr"
        "120000"
    """
    if not text:
        return None, None

    text = text.replace(",", "").replace("$", "").strip()

    # Match ranges: "120000 - 150000", "80K-100K"
    range_match = re.search(r"(\d+\.?\d*)\s*[kK]?\s*[-–to]+\s*(\d+\.?\d*)\s*[kK]?", text)
    if range_match:
        low = _normalize_salary(range_match.group(1), "K" in text.upper())
        high = _normalize_salary(range_match.group(2), "K" in text.upper())
        return low, high

    # Single value: "150000", "150K"
    single_match = re.search(r"(\d+\.?\d*)\s*[kK]?", text)
    if single_match:
        val = _normalize_salary(single_match.group(1), "K" in text.upper())
        return val, None

    return None, None


def _normalize_salary(val_str: str, has_k: bool) -> int:
    """Convert a numeric string to an integer salary."""
    val = float(val_str)
    if has_k and val < 1000:
        val *= 1000
    return int(val)


def detect_remote(location: str | None, title: str | None = None) -> bool:
    """Return True if the job appears to be remote."""
    for text in (location, title):
        if text and re.search(r"\bremote\b", text, re.IGNORECASE):
            return True
    return False


def parse_relative_date(text: str | None) -> datetime | None:
    """Parse relative date strings like '3 days ago', 'Just posted', '1 hour ago'.

    Returns a timezone-aware UTC datetime or None.
    """
    if not text:
        return None

    text = text.strip().lower()
    now = datetime.now(timezone.utc)

    if "just" in text or "today" in text or "now" in text:
        return now

    if "yesterday" in text:
        return now - timedelta(days=1)

    # Strip "+" so "30+ Days Ago" becomes "30 Days Ago"
    text = text.replace("+", "")

    match = re.search(r"(\d+)\s*(second|minute|hour|day|week|month)", text)
    if not match:
        return None

    amount = int(match.group(1))
    unit = match.group(2)

    deltas = {
        "second": timedelta(seconds=amount),
        "minute": timedelta(minutes=amount),
        "hour": timedelta(hours=amount),
        "day": timedelta(days=amount),
        "week": timedelta(weeks=amount),
        "month": timedelta(days=amount * 30),
    }

    return now - deltas.get(unit, timedelta())

"""Load golden test sets and convert to LLM prompts using verifier functions."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from .schema import GoldenTestCase, GoldenTestSet

log = logging.getLogger(__name__)

# System prompt — identical to verifier/graph/nodes.py:57 and discovery.py:525.
LLM_SYSTEM_PROMPT = (
    "You pick the best navigation element from a webpage for a given goal. "
    "Reply with ONLY the element number (e.g. '7') or 'NONE' if no element matches. "
    "Do not explain."
)

# Max candidates sent to the LLM (matches verifier's _MAX_LLM_CANDIDATES).
_MAX_LLM_CANDIDATES = 30

# Patterns to exclude (matches verifier's _is_excluded).
_EXCLUDE_RE = re.compile(
    r"^(#|javascript:|mailto:|tel:)", re.IGNORECASE
)


def load_golden_set(path: Path) -> GoldenTestSet:
    """Load and validate a golden test set from a JSON file."""
    with open(path) as f:
        data = json.load(f)
    return GoldenTestSet.model_validate(data)


def load_all_golden_sets(directory: Path) -> list[GoldenTestSet]:
    """Load all golden test set JSON files from a directory."""
    sets = []
    for p in sorted(directory.glob("element_pick_*.json")):
        try:
            sets.append(load_golden_set(p))
            log.info("Loaded golden set: %s (%d cases)", p.name, len(sets[-1].cases))
        except Exception:
            log.warning("Failed to load golden set %s", p, exc_info=True)
    return sets


def prepare_elements(elements: list[dict]) -> list[dict]:
    """Filter and number elements for LLM consumption.

    Mirrors ``verifier.checks.discovery._prepare_elements_for_llm`` but
    operates on plain dicts so the benchmark has no Playwright dependency.
    """
    candidates = []
    for i, el in enumerate(elements):
        if not el.get("visible", True):
            continue
        text = el.get("text", "").strip()
        aria = el.get("aria", "").strip()
        if not text and not aria:
            continue
        href = el.get("href", "").strip()
        if _EXCLUDE_RE.match(href):
            continue
        candidates.append({**el, "idx": i})

    if len(candidates) > _MAX_LLM_CANDIDATES:
        structural = [
            c for c in candidates
            if c.get("inNav") or c.get("inHeader") or c.get("inFooter")
        ]
        other = [
            c for c in candidates
            if not (c.get("inNav") or c.get("inHeader") or c.get("inFooter"))
        ]
        candidates = structural + other[: _MAX_LLM_CANDIDATES - len(structural)]
        candidates = candidates[:_MAX_LLM_CANDIDATES]

    return candidates


def build_llm_prompt(candidates: list[dict], goal: str) -> str:
    """Build a compact prompt listing candidate elements.

    Mirrors ``verifier.checks.discovery._build_llm_prompt``.
    """
    if goal == "careers":
        instruction = (
            "Which element most likely leads to this company's careers or jobs page? "
            "Look for links about working at the company, open positions, hiring, "
            "team culture, or an applicant tracking system."
        )
    else:
        instruction = (
            "Which element most likely leads to this company's contact page? "
            "Look for links about contacting the company, getting in touch, "
            "reaching the team, or finding email/phone info."
        )

    lines = [instruction, "", "Elements:"]
    for i, c in enumerate(candidates):
        text = c.get("text", "")[:80]
        href = c.get("href", "")[:120]
        aria = c.get("aria", "")[:40]
        location = []
        if c.get("inNav"):
            location.append("nav")
        if c.get("inHeader"):
            location.append("header")
        if c.get("inFooter"):
            location.append("footer")
        loc_str = ",".join(location) if location else "body"

        line = f"{i} | {text}"
        if aria and aria.lower() != text.lower():
            line += f" [aria: {aria}]"
        line += f" | {href} | {loc_str}"
        lines.append(line)

    return "\n".join(lines)


_LLM_PICK_RE = re.compile(r"^\s*(\d+)\s*$")


def parse_llm_response(content: str, candidates: list[dict]) -> int | None:
    """Parse LLM response into a candidate index.

    Mirrors ``verifier.graph.nodes._parse_llm_content`` but returns the
    index rather than the element dict.
    """
    content = content.strip()
    if content.upper() == "NONE":
        return None

    m = _LLM_PICK_RE.match(content)
    if not m:
        numbers = re.findall(r"\b(\d+)\b", content)
        if not numbers:
            return None
        idx = int(numbers[0])
    else:
        idx = int(m.group(1))

    if 0 <= idx < len(candidates):
        return idx
    return None


def case_to_prompt(case: GoldenTestCase) -> tuple[str, str, list[dict]]:
    """Convert a golden test case to (system_prompt, user_prompt, candidates).

    Returns the candidates list so the caller can use ``parse_llm_response``
    with the same candidate ordering.
    """
    elements = [el.model_dump() for el in case.elements]
    candidates = prepare_elements(elements)
    user_prompt = build_llm_prompt(candidates, case.goal)
    return LLM_SYSTEM_PROMPT, user_prompt, candidates

"""Confidence gating: label captured cascade results for training vs evaluation.

The cascade's confidence signals determine whether an output becomes a
high-confidence training example or a low-confidence edge case for evaluation.

Key signal: when the LLM picks an element AND downstream ATS detection confirms
it was correct, that's a high-confidence positive. When all layers fail, that's
a high-confidence negative (NONE).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .capture import CapturedResult

log = logging.getLogger(__name__)


@dataclass
class LabeledExample:
    """A captured result with a confidence label and correct answer."""

    captured: CapturedResult
    label: Literal[
        "high_conf_pick",
        "high_conf_none",
        "low_conf_pick",
        "low_conf_none",
    ]
    goal: str  # "careers" or "contact"
    correct_answer_idx: int | None  # index into prepared candidates, or None for NONE
    confidence_reason: str


def label_captured_results(
    results: list[CapturedResult],
) -> tuple[list[LabeledExample], list[LabeledExample]]:
    """Split results into high-confidence training examples and low-confidence edge cases.

    Returns:
        (high_confidence, low_confidence) — each a list of LabeledExample.
    """
    high_conf: list[LabeledExample] = []
    low_conf: list[LabeledExample] = []

    for r in results:
        # Skip errors and nav failures.
        if r.error or r.nav_failed:
            continue
        if not r.elements:
            continue

        # Label careers goal.
        _label_careers(r, high_conf, low_conf)

    stats = {
        "total": len(results),
        "errors": sum(1 for r in results if r.error),
        "nav_failed": sum(1 for r in results if r.nav_failed),
        "high_conf": len(high_conf),
        "low_conf": len(low_conf),
    }
    log.info("Labeling stats: %s", stats)
    return high_conf, low_conf


def _label_careers(
    r: CapturedResult,
    high_conf: list[LabeledExample],
    low_conf: list[LabeledExample],
) -> None:
    """Label a single result for the careers goal."""
    source = r.careers_source
    ats = r.careers.get("ats_platform")
    careers_url = r.careers.get("careers_url")

    if source == "dom":
        # DOM scoring is deterministic and high confidence.
        idx = _find_pick_index(r)
        if idx is not None:
            high_conf.append(LabeledExample(
                captured=r,
                label="high_conf_pick",
                goal="careers",
                correct_answer_idx=idx,
                confidence_reason=f"DOM pick confirmed (ats={ats})",
            ))

    elif source in ("llm", "vision"):
        if ats:
            # LLM/Vision picked + ATS confirmed downstream.
            idx = _find_pick_index(r)
            if idx is not None:
                high_conf.append(LabeledExample(
                    captured=r,
                    label="high_conf_pick",
                    goal="careers",
                    correct_answer_idx=idx,
                    confidence_reason=f"{source} pick, ATS={ats} confirmed",
                ))
        elif careers_url:
            # LLM/Vision picked but no ATS — uncertain.
            idx = _find_pick_index(r)
            low_conf.append(LabeledExample(
                captured=r,
                label="low_conf_pick",
                goal="careers",
                correct_answer_idx=idx,
                confidence_reason=f"{source} pick, no ATS confirmation, url={careers_url}",
            ))
        else:
            # LLM/Vision picked but navigation found nothing.
            low_conf.append(LabeledExample(
                captured=r,
                label="low_conf_pick",
                goal="careers",
                correct_answer_idx=_find_pick_index(r),
                confidence_reason=f"{source} pick, navigation failed",
            ))

    elif source == "probe":
        # Probe succeeded but LLM/vision/DOM all failed.
        # This means the LLM SHOULD have picked something but said NONE.
        # Try to find which element matches the probed URL.
        idx = _match_probe_to_element(r)
        if idx is not None:
            # We know the correct element — valuable NONE-correction example.
            high_conf.append(LabeledExample(
                captured=r,
                label="low_conf_none",
                goal="careers",
                correct_answer_idx=idx,
                confidence_reason=f"Probe found careers (ats={ats}), matched to element {idx}",
            ))
        else:
            # Probe found a careers page but no element links to it.
            low_conf.append(LabeledExample(
                captured=r,
                label="low_conf_none",
                goal="careers",
                correct_answer_idx=None,
                confidence_reason="Probe found careers but no matching element",
            ))

    elif source == "none":
        # All layers failed — high-confidence NONE.
        high_conf.append(LabeledExample(
            captured=r,
            label="high_conf_none",
            goal="careers",
            correct_answer_idx=None,
            confidence_reason="All 4 layers failed to find careers",
        ))


def _find_pick_index(r: CapturedResult) -> int | None:
    """Find the index of best_careers_el within the prepared candidate list.

    The benchmark's prepare_elements() filters and re-indexes elements.
    We need to find the picked element's position in that prepared list.
    """
    from benchmark.golden.loader import prepare_elements

    if not r.best_careers_el:
        return None

    candidates = prepare_elements(r.elements)
    if not candidates:
        return None

    # Match by the 'idx' field (original element index) set by prepare_elements.
    pick_idx = r.best_careers_el.get("idx")
    if pick_idx is not None:
        for i, c in enumerate(candidates):
            if c.get("idx") == pick_idx:
                return i

    # Fallback: match by href + text.
    pick_href = r.best_careers_el.get("href", "")
    pick_text = r.best_careers_el.get("text", "")
    for i, c in enumerate(candidates):
        if c.get("href") == pick_href and c.get("text") == pick_text:
            return i

    log.debug("Could not find pick in candidates for %s", r.company_name)
    return None


def _match_probe_to_element(r: CapturedResult) -> int | None:
    """Try to find which element's href matches the probe-discovered careers URL.

    When probe_fallback succeeds but LLM/vision failed, we check if any
    navigable element on the page would have led to the careers URL.
    """
    from benchmark.golden.loader import prepare_elements

    careers_url = r.careers.get("careers_url", "")
    if not careers_url:
        return None

    candidates = prepare_elements(r.elements)
    if not candidates:
        return None

    # Normalize for comparison.
    careers_lower = careers_url.lower().rstrip("/")

    for i, c in enumerate(candidates):
        href = c.get("href", "").lower().rstrip("/")
        if not href:
            continue
        # Exact match or prefix match.
        if href == careers_lower or careers_lower.startswith(href):
            return i
        # Check if the element href is a path that matches.
        if href in careers_lower:
            return i

    return None

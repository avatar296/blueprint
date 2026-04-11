"""Convert low-confidence captured results to golden test set format for evaluation."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from benchmark.golden.schema import ElementCandidate, GoldenTestCase, GoldenTestSet

from .filter import LabeledExample

log = logging.getLogger(__name__)


def build_edge_case_golden_set(
    low_confidence: list[LabeledExample],
    output_path: Path,
    goal: str = "careers",
) -> GoldenTestSet:
    """Convert low-confidence captures to GoldenTestSet format.

    These cases need manual review of expected_pick_idx before use
    as ground truth. The heuristic best-guess is included but may be wrong.

    Output format matches ``benchmark/golden_data/element_pick_careers.json``.
    """
    cases: list[GoldenTestCase] = []

    for i, ex in enumerate(low_confidence):
        if ex.goal != goal:
            continue

        r = ex.captured
        elements = []
        for el in r.elements:
            elements.append(ElementCandidate(
                text=el.get("text", ""),
                href=el.get("href", ""),
                aria=el.get("aria", ""),
                visible=el.get("visible", True),
                inNav=el.get("inNav", False),
                inHeader=el.get("inHeader", False),
                inFooter=el.get("inFooter", False),
            ))

        pick_text = None
        if ex.correct_answer_idx is not None and ex.correct_answer_idx < len(elements):
            pick_text = elements[ex.correct_answer_idx].text

        cases.append(GoldenTestCase(
            id=f"edge-{goal}-{i:03d}",
            company_name=r.company_name,
            url=r.url,
            goal=goal,
            elements=elements,
            expected_pick_idx=ex.correct_answer_idx,
            expected_pick_text=pick_text,
            difficulty="hard",
            notes=(
                f"Source: {r.careers_source}. "
                f"Label: {ex.label}. "
                f"Reason: {ex.confidence_reason}. "
                f"NEEDS MANUAL REVIEW."
            ),
        ))

    golden_set = GoldenTestSet(
        version="1.0",
        goal=goal,
        cases=cases,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(golden_set.model_dump(), f, indent=2)

    log.info("Wrote %d edge cases to %s", len(cases), output_path)
    return golden_set

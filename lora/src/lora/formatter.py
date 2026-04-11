"""Convert labeled examples to JSONL training data for LoRA fine-tuning.

Uses the same prompt-building functions as the benchmark harness to ensure
training prompts match the inference distribution exactly.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from benchmark.golden.loader import LLM_SYSTEM_PROMPT, build_llm_prompt, prepare_elements

from .filter import LabeledExample

log = logging.getLogger(__name__)


def format_training_data(
    labeled: list[LabeledExample],
    output_path: Path,
    *,
    none_oversample: float = 2.0,
) -> int:
    """Convert labeled examples to JSONL training data.

    Args:
        labeled: High-confidence labeled examples from filter.py.
        output_path: Where to write JSONL.
        none_oversample: Repeat factor for NONE examples to combat
            false-pick bias. Default 2.0 = NONE examples appear twice.

    Returns:
        Number of training examples written.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    count = 0
    skipped = 0
    none_count = 0
    pick_count = 0

    with open(output_path, "w") as f:
        for ex in labeled:
            example = _to_training_example(ex)
            if example is None:
                skipped += 1
                continue

            # Write the example.
            f.write(json.dumps(example) + "\n")
            count += 1

            is_none = example["messages"][-1]["content"] == "NONE"
            if is_none:
                none_count += 1
                # Oversample NONE examples.
                extra = int(none_oversample) - 1
                for _ in range(extra):
                    f.write(json.dumps(example) + "\n")
                    count += 1
            else:
                pick_count += 1

    log.info(
        "Wrote %d training examples (%d picks, %d NONEs including %.0fx oversample, %d skipped) to %s",
        count, pick_count, none_count, none_oversample, skipped, output_path,
    )
    return count


def _to_training_example(ex: LabeledExample) -> dict | None:
    """Convert a single labeled example to a training JSONL line.

    Returns None if the example can't be converted (missing elements, etc).
    """
    elements = ex.captured.elements
    if not elements:
        return None

    # Build prompt through the same pipeline as production.
    candidates = prepare_elements(elements)
    if not candidates:
        return None

    user_prompt = build_llm_prompt(candidates, ex.goal)

    # Determine the correct assistant response.
    if ex.correct_answer_idx is None:
        answer = "NONE"
    else:
        if ex.correct_answer_idx < 0 or ex.correct_answer_idx >= len(candidates):
            log.debug(
                "Answer index %d out of range for %s (%d candidates)",
                ex.correct_answer_idx, ex.captured.company_name, len(candidates),
            )
            return None
        answer = str(ex.correct_answer_idx)

    return {
        "messages": [
            {"role": "system", "content": LLM_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
            {"role": "assistant", "content": answer},
        ]
    }


def write_generation_stats(
    high_conf: list[LabeledExample],
    low_conf: list[LabeledExample],
    training_count: int,
    output_path: Path,
) -> None:
    """Write generation statistics to JSON."""
    stats = {
        "high_confidence_total": len(high_conf),
        "low_confidence_total": len(low_conf),
        "training_examples_written": training_count,
        "high_conf_by_label": {},
        "low_conf_by_label": {},
        "high_conf_by_source": {},
    }

    for ex in high_conf:
        stats["high_conf_by_label"][ex.label] = stats["high_conf_by_label"].get(ex.label, 0) + 1
        src = ex.captured.careers_source
        stats["high_conf_by_source"][src] = stats["high_conf_by_source"].get(src, 0) + 1

    for ex in low_conf:
        stats["low_conf_by_label"][ex.label] = stats["low_conf_by_label"].get(ex.label, 0) + 1

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(stats, f, indent=2)
    log.info("Generation stats: %s", stats)

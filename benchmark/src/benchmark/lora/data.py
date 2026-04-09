"""Generate JSONL training data from golden test sets."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..golden.loader import case_to_prompt, load_all_golden_sets

log = logging.getLogger(__name__)


def generate_training_template(
    golden_data_dir: Path,
    output_path: Path,
) -> None:
    """Convert golden test sets into JSONL training data for LoRA fine-tuning.

    Each line is a chat-format training example:
    {
        "messages": [
            {"role": "system", "content": "<system prompt>"},
            {"role": "user", "content": "<formatted elements>"},
            {"role": "assistant", "content": "<correct answer>"}
        ]
    }
    """
    golden_sets = load_all_golden_sets(golden_data_dir)
    if not golden_sets:
        log.error("No golden test sets found in %s", golden_data_dir)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0

    with open(output_path, "w") as f:
        for gs in golden_sets:
            for case in gs.cases:
                system_prompt, user_prompt, candidates = case_to_prompt(case)

                # Build the correct assistant response.
                if case.expected_pick_idx is None:
                    answer = "NONE"
                else:
                    answer = str(case.expected_pick_idx)

                example = {
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                        {"role": "assistant", "content": answer},
                    ]
                }
                f.write(json.dumps(example) + "\n")
                count += 1

    log.info("Generated %d training examples to %s", count, output_path)

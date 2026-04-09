"""Scoring: precision, recall, F1, confusion matrix for benchmark results."""

from __future__ import annotations

from collections import defaultdict

from ..golden.schema import CaseResult, VariantScore


def score_variant(
    model_id: str,
    quant_level: str,
    is_lora: bool,
    results: list[CaseResult],
    backend: str = "ollama",
) -> VariantScore:
    """Compute aggregate scores for a single model variant."""
    if not results:
        return VariantScore(
            model_id=model_id,
            quant_level=quant_level,
            is_lora=is_lora,
            backend=backend,
        )

    total = len(results)
    correct = sum(1 for r in results if r.correct)

    # Confusion matrix bins.
    cm: dict[str, int] = defaultdict(int)
    for r in results:
        if r.expected_idx is None and r.predicted_idx is None:
            cm["true_none"] += 1
        elif r.expected_idx is None and r.predicted_idx is not None:
            cm["false_pick"] += 1
        elif r.expected_idx is not None and r.predicted_idx is None:
            cm["false_none"] += 1
        elif r.predicted_idx == r.expected_idx:
            cm["correct_pick"] += 1
        else:
            cm["wrong_pick"] += 1

    # Per-goal precision/recall/F1.
    by_goal: dict[str, list[CaseResult]] = defaultdict(list)
    for r in results:
        # Infer goal from case_id prefix.
        goal = r.case_id.split("-")[0] if "-" in r.case_id else "unknown"
        by_goal[goal].append(r)

    precision_by_goal: dict[str, float] = {}
    recall_by_goal: dict[str, float] = {}
    f1_by_goal: dict[str, float] = {}

    for goal, goal_results in by_goal.items():
        # True positive: predicted correctly (not NONE when expected not NONE).
        tp = sum(1 for r in goal_results if r.correct and r.expected_idx is not None)
        # False positive: predicted something when should have been NONE, or predicted wrong.
        fp = sum(
            1 for r in goal_results
            if not r.correct and r.predicted_idx is not None
        )
        # False negative: predicted NONE when should have picked something.
        fn = sum(
            1 for r in goal_results
            if not r.correct and r.predicted_idx is None and r.expected_idx is not None
        )

        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall) > 0
            else 0.0
        )

        precision_by_goal[goal] = round(precision, 4)
        recall_by_goal[goal] = round(recall, 4)
        f1_by_goal[goal] = round(f1, 4)

    # None rates.
    none_predictions = sum(1 for r in results if r.predicted_idx is None)
    false_nones = cm.get("false_none", 0)
    expected_picks = sum(1 for r in results if r.expected_idx is not None)

    return VariantScore(
        model_id=model_id,
        quant_level=quant_level,
        is_lora=is_lora,
        backend=backend,
        accuracy=round(correct / total, 4),
        precision_by_goal=precision_by_goal,
        recall_by_goal=recall_by_goal,
        f1_by_goal=f1_by_goal,
        confusion_matrix=dict(cm),
        none_rate=round(none_predictions / total, 4) if total > 0 else 0.0,
        false_none_rate=round(false_nones / expected_picks, 4) if expected_picks > 0 else 0.0,
        total_cases=total,
    )

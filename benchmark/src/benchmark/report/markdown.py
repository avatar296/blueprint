"""Markdown report generation."""

from __future__ import annotations

import logging
from pathlib import Path

from ..golden.schema import ParetoPoint, VariantMetrics, VariantScore

log = logging.getLogger(__name__)


def generate_report(
    scores: list[VariantScore],
    metrics: list[VariantMetrics],
    pareto: list[ParetoPoint],
    output_dir: Path,
) -> None:
    """Generate a markdown comparison report."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "comparison_report.md"

    metrics_by_id = {m.model_id: m for m in metrics}
    pareto_by_id = {p.model_id: p for p in pareto}

    lines: list[str] = []
    lines.append("# KYB Quantization & LoRA Benchmark Report\n")
    lines.append("## Comparison Table\n")
    lines.append(
        "| Variant | Quant | LoRA | Accuracy | P50 (ms) | P95 (ms) | "
        "Mem (MB) | Tok/s | $/1K | Pareto |"
    )
    lines.append(
        "|---------|-------|------|----------|----------|----------|"
        "----------|-------|------|--------|"
    )

    for score in scores:
        m = metrics_by_id.get(score.model_id)
        p = pareto_by_id.get(score.model_id)
        if not m:
            continue

        pareto_flag = "**Yes**" if (p and p.is_pareto_optimal) else ""
        lora_flag = "Yes" if score.is_lora else ""

        lines.append(
            f"| {score.model_id} | {score.quant_level} | {lora_flag} | "
            f"{score.accuracy:.1%} | {m.latency_p50_ms:.1f} | {m.latency_p95_ms:.1f} | "
            f"{m.model_memory_mb:.0f} | {m.tokens_per_second:.1f} | "
            f"${m.estimated_cost_per_1k_queries:.4f} | {pareto_flag} |"
        )

    lines.append("")

    # Per-goal breakdown.
    lines.append("## Per-Goal Metrics\n")
    lines.append("| Variant | Goal | Precision | Recall | F1 |")
    lines.append("|---------|------|-----------|--------|----|")

    for score in scores:
        all_goals = set(score.precision_by_goal) | set(score.recall_by_goal)
        for goal in sorted(all_goals):
            prec = score.precision_by_goal.get(goal, 0)
            rec = score.recall_by_goal.get(goal, 0)
            f1 = score.f1_by_goal.get(goal, 0)
            lines.append(
                f"| {score.model_id} | {goal} | {prec:.3f} | {rec:.3f} | {f1:.3f} |"
            )

    lines.append("")

    # Confusion matrix summary.
    lines.append("## Confusion Matrix Summary\n")
    lines.append(
        "| Variant | Correct Pick | Wrong Pick | False None | True None | False Pick | None Rate |"
    )
    lines.append(
        "|---------|-------------|------------|------------|-----------|------------|-----------|"
    )

    for score in scores:
        cm = score.confusion_matrix
        lines.append(
            f"| {score.model_id} | "
            f"{cm.get('correct_pick', 0)} | {cm.get('wrong_pick', 0)} | "
            f"{cm.get('false_none', 0)} | {cm.get('true_none', 0)} | "
            f"{cm.get('false_pick', 0)} | {score.none_rate:.1%} |"
        )

    lines.append("")

    # Pareto analysis.
    pareto_opts = [p for p in pareto if p.is_pareto_optimal]
    if pareto_opts:
        lines.append("## Pareto-Optimal Configurations\n")
        lines.append(
            "These variants are not dominated by any other variant on accuracy, "
            "latency, and cost combined:\n"
        )
        for p in pareto_opts:
            lines.append(
                f"- **{p.model_id}**: accuracy={p.accuracy:.1%}, "
                f"p50={p.latency_p50_ms:.1f}ms, "
                f"mem={p.memory_mb:.0f}MB, "
                f"cost=${p.cost_per_1k:.4f}/1K queries"
            )
        lines.append("")

    # Plots.
    lines.append("## Visualizations\n")
    lines.append("![Accuracy vs Cost](accuracy_vs_cost.png)\n")
    lines.append("![Latency Distributions](latency_distributions.png)\n")
    lines.append("![Memory Comparison](memory_comparison.png)\n")
    lines.append("![Confusion Matrices](confusion_matrices.png)\n")

    report_text = "\n".join(lines)
    output_path.write_text(report_text)
    log.info("Saved markdown report to %s", output_path)

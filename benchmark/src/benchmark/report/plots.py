"""Matplotlib visualizations for benchmark results."""

from __future__ import annotations

import logging
from pathlib import Path

from ..golden.schema import ParetoPoint, VariantMetrics, VariantScore

log = logging.getLogger(__name__)

# Quant level -> color mapping.
_QUANT_COLORS = {
    "fp16": "#2563eb",   # blue
    "q8_0": "#16a34a",   # green
    "q4_0": "#dc2626",   # red
    "q4_k_m": "#ea580c",  # orange
    "q5_k_m": "#9333ea",  # purple
}

# LoRA marker styles.
_BASE_MARKER = "o"
_LORA_MARKER = "^"


def plot_accuracy_vs_cost(
    pareto: list[ParetoPoint],
    output_path: Path,
) -> None:
    """Scatter plot: accuracy (y) vs estimated cost (x).

    Colored by quantization level, shaped by LoRA status.
    Pareto-optimal points are highlighted with a gold border.
    """
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 7))

    for p in pareto:
        color = _QUANT_COLORS.get(p.quant_level, "#6b7280")
        marker = _LORA_MARKER if p.is_lora else _BASE_MARKER
        edge_color = "#f59e0b" if p.is_pareto_optimal else color
        edge_width = 3 if p.is_pareto_optimal else 1

        ax.scatter(
            p.cost_per_1k, p.accuracy * 100,
            c=color, marker=marker, s=200, zorder=5,
            edgecolors=edge_color, linewidths=edge_width,
        )
        label = p.model_id.split(":")[-1] if ":" in p.model_id else p.model_id
        if p.is_lora:
            label += " (LoRA)"
        ax.annotate(
            label,
            (p.cost_per_1k, p.accuracy * 100),
            textcoords="offset points", xytext=(8, 5),
            fontsize=9, alpha=0.8,
        )

    ax.set_xlabel("Estimated Cost per 1K Queries ($)", fontsize=12)
    ax.set_ylabel("Accuracy (%)", fontsize=12)
    ax.set_title("Quantization Cost-Quality Tradeoff", fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)

    # Legend.
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], marker=_BASE_MARKER, color="w", markerfacecolor="#6b7280",
               markersize=10, label="Base model"),
        Line2D([0], [0], marker=_LORA_MARKER, color="w", markerfacecolor="#6b7280",
               markersize=10, label="LoRA model"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="w",
               markeredgecolor="#f59e0b", markeredgewidth=2, markersize=10,
               label="Pareto optimal"),
    ]
    for level, color in _QUANT_COLORS.items():
        if any(p.quant_level == level for p in pareto):
            legend_elements.append(
                Line2D([0], [0], marker="s", color="w", markerfacecolor=color,
                       markersize=10, label=level.upper())
            )
    ax.legend(handles=legend_elements, loc="lower right", fontsize=9)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved accuracy vs cost plot to %s", output_path)


def plot_latency_distributions(
    metrics: list[VariantMetrics],
    raw_latencies: dict[str, list[float]],
    output_path: Path,
) -> None:
    """Box plots of latency distributions per model variant."""
    import matplotlib.pyplot as plt

    if not raw_latencies:
        log.warning("No raw latency data — skipping latency distribution plot")
        return

    fig, ax = plt.subplots(figsize=(12, 6))

    labels = []
    data = []
    colors = []

    for m in metrics:
        if m.model_id in raw_latencies:
            lats = raw_latencies[m.model_id]
            if lats:
                label = m.model_id.split(":")[-1] if ":" in m.model_id else m.model_id
                if m.is_lora:
                    label += "\n(LoRA)"
                labels.append(label)
                data.append(lats)
                colors.append(_QUANT_COLORS.get(m.quant_level, "#6b7280"))

    if not data:
        plt.close(fig)
        return

    bp = ax.boxplot(
        data, labels=labels, patch_artist=True,
        whiskerprops={"alpha": 0.5},
        flierprops={"alpha": 0.3, "markersize": 3},
    )

    for patch, color in zip(bp["boxes"], colors):
        patch.set_facecolor(color)
        patch.set_alpha(0.6)

    ax.set_ylabel("Latency (ms)", fontsize=12)
    ax.set_title("Latency Distributions by Model Variant", fontsize=14, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved latency distributions plot to %s", output_path)


def plot_memory_comparison(
    metrics: list[VariantMetrics],
    output_path: Path,
) -> None:
    """Bar chart of model memory footprint per variant."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 6))

    labels = []
    mem_values = []
    colors = []

    for m in metrics:
        label = m.model_id.split(":")[-1] if ":" in m.model_id else m.model_id
        if m.is_lora:
            label += " (LoRA)"
        labels.append(label)
        mem_values.append(m.model_memory_mb)
        colors.append(_QUANT_COLORS.get(m.quant_level, "#6b7280"))

    bars = ax.bar(labels, mem_values, color=colors, alpha=0.7, edgecolor="white")

    for bar, val in zip(bars, mem_values):
        if val > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2, bar.get_height() + 20,
                f"{val:.0f}MB", ha="center", va="bottom", fontsize=9,
            )

    ax.set_ylabel("Model Memory (MB)", fontsize=12)
    ax.set_title("Memory Footprint by Model Variant", fontsize=14, fontweight="bold")
    ax.grid(True, axis="y", alpha=0.3)

    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved memory comparison plot to %s", output_path)


def plot_confusion_matrices(
    scores: list[VariantScore],
    output_path: Path,
) -> None:
    """Grid of confusion matrices, one per variant."""
    import matplotlib.pyplot as plt

    n = len(scores)
    if n == 0:
        return

    cols = min(n, 3)
    rows = (n + cols - 1) // cols
    fig, axes = plt.subplots(rows, cols, figsize=(5 * cols, 4 * rows), squeeze=False)

    categories = ["correct_pick", "wrong_pick", "false_none", "true_none", "false_pick"]
    display_labels = ["Correct\nPick", "Wrong\nPick", "False\nNone", "True\nNone", "False\nPick"]

    for idx, score in enumerate(scores):
        r, c = divmod(idx, cols)
        ax = axes[r][c]

        values = [score.confusion_matrix.get(cat, 0) for cat in categories]
        total = sum(values) or 1
        fracs = [v / total for v in values]

        bar_colors = ["#16a34a", "#dc2626", "#f59e0b", "#6b7280", "#ea580c"]
        ax.bar(display_labels, fracs, color=bar_colors, alpha=0.7)
        ax.set_ylim(0, 1.0)
        ax.set_ylabel("Fraction")

        title = score.model_id.split(":")[-1] if ":" in score.model_id else score.model_id
        if score.is_lora:
            title += " (LoRA)"
        ax.set_title(f"{title}\nacc={score.accuracy:.1%}", fontsize=10)
        ax.tick_params(axis="x", labelsize=8)

    # Hide unused subplots.
    for idx in range(n, rows * cols):
        r, c = divmod(idx, cols)
        axes[r][c].set_visible(False)

    fig.suptitle("Confusion Matrix Breakdown", fontsize=14, fontweight="bold")
    fig.tight_layout()
    fig.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    log.info("Saved confusion matrices plot to %s", output_path)


def generate_all_plots(
    scores: list[VariantScore],
    metrics: list[VariantMetrics],
    pareto: list[ParetoPoint],
    raw_latencies: dict[str, list[float]],
    output_dir: Path,
) -> None:
    """Generate all benchmark visualization plots."""
    output_dir.mkdir(parents=True, exist_ok=True)

    plot_accuracy_vs_cost(pareto, output_dir / "accuracy_vs_cost.png")
    plot_latency_distributions(metrics, raw_latencies, output_dir / "latency_distributions.png")
    plot_memory_comparison(metrics, output_dir / "memory_comparison.png")
    plot_confusion_matrices(scores, output_dir / "confusion_matrices.png")

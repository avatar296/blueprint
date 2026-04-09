"""Pareto-optimal configuration identification."""

from __future__ import annotations

from ..golden.schema import ParetoPoint, VariantMetrics, VariantScore


def find_pareto_optimal(
    scores: list[VariantScore],
    metrics: list[VariantMetrics],
) -> list[ParetoPoint]:
    """Identify Pareto-optimal variants on the accuracy vs cost frontier.

    A point is Pareto-optimal if no other point is strictly better on ALL
    of: accuracy (higher), latency (lower), cost (lower).
    """
    if not scores or not metrics:
        return []

    # Build metric lookup.
    metrics_by_id = {m.model_id: m for m in metrics}

    points: list[ParetoPoint] = []
    for score in scores:
        m = metrics_by_id.get(score.model_id)
        if not m:
            continue
        points.append(ParetoPoint(
            model_id=score.model_id,
            quant_level=score.quant_level,
            is_lora=score.is_lora,
            accuracy=score.accuracy,
            latency_p50_ms=m.latency_p50_ms,
            memory_mb=m.model_memory_mb,
            cost_per_1k=m.estimated_cost_per_1k_queries,
        ))

    # Mark Pareto-optimal points.
    for i, p in enumerate(points):
        dominated = False
        for j, q in enumerate(points):
            if i == j:
                continue
            # q dominates p if q is >= on all objectives and strictly > on at least one.
            if (
                q.accuracy >= p.accuracy
                and q.latency_p50_ms <= p.latency_p50_ms
                and q.cost_per_1k <= p.cost_per_1k
                and (
                    q.accuracy > p.accuracy
                    or q.latency_p50_ms < p.latency_p50_ms
                    or q.cost_per_1k < p.cost_per_1k
                )
            ):
                dominated = True
                break
        p.is_pareto_optimal = not dominated

    return points

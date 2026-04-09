"""Metrics collection: latency percentiles, GPU memory, cost estimation."""

from __future__ import annotations

import asyncio
import logging
import statistics

import httpx

from ..golden.schema import CaseResult, VariantMetrics

log = logging.getLogger(__name__)


def compute_latency_percentiles(latencies: list[float]) -> dict[str, float]:
    """Compute p50, p95, p99, and mean from a list of latency values (ms)."""
    if not latencies:
        return {"p50": 0.0, "p95": 0.0, "p99": 0.0, "mean": 0.0}

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)

    def _percentile(p: float) -> float:
        k = (p / 100) * (n - 1)
        f = int(k)
        c = f + 1 if f + 1 < n else f
        d = k - f
        return sorted_lat[f] + d * (sorted_lat[c] - sorted_lat[f])

    return {
        "p50": _percentile(50),
        "p95": _percentile(95),
        "p99": _percentile(99),
        "mean": statistics.mean(sorted_lat),
    }


def compute_tokens_per_second(results: list[CaseResult]) -> float:
    """Compute average tokens per second across all results."""
    total_tokens = 0
    total_time_s = 0.0
    for r in results:
        total_tokens += r.completion_tokens
        total_time_s += r.latency_ms / 1000
    if total_time_s <= 0:
        return 0.0
    return total_tokens / total_time_s


async def collect_gpu_memory_nvidia_smi() -> float | None:
    """Run nvidia-smi to get total GPU memory usage in MB."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "nvidia-smi",
            "--query-gpu=memory.used",
            "--format=csv,noheader,nounits",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        # Sum across all GPUs.
        total = sum(
            float(line.strip())
            for line in stdout.decode().strip().split("\n")
            if line.strip()
        )
        return total
    except FileNotFoundError:
        log.debug("nvidia-smi not found")
        return None
    except Exception:
        log.debug("nvidia-smi failed", exc_info=True)
        return None


async def collect_ollama_memory(base_url: str, model_tag: str) -> float:
    """Query Ollama /api/ps for memory used by a specific model (MB)."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{base_url}/api/ps")
            resp.raise_for_status()
            data = resp.json()

        model_prefix = model_tag.split(":")[0]
        for model in data.get("models", []):
            name = model.get("name", "")
            if name == model_tag or name.startswith(model_prefix):
                return model.get("size", 0) / (1024 * 1024)
        return 0.0
    except Exception:
        log.debug("Failed to query Ollama /api/ps", exc_info=True)
        return 0.0


# Cloud GPU hourly rates (USD).
_GPU_RATES = {
    "T4": 0.35,
    "A10G": 0.80,
    "A100": 2.21,
}


def estimate_cost_per_1k(
    latency_mean_ms: float,
    gpu_type: str = "A10G",
    custom_rates: dict[str, float] | None = None,
) -> float:
    """Estimate cost per 1,000 queries based on GPU-hour pricing.

    Cost = (latency_per_query * 1000 queries) / 3600s * hourly_rate
    """
    rates = custom_rates or _GPU_RATES
    hourly_rate = rates.get(gpu_type, rates.get("A10G", 0.80))
    if latency_mean_ms <= 0:
        return 0.0
    total_seconds = (latency_mean_ms / 1000) * 1000
    gpu_hours = total_seconds / 3600
    return gpu_hours * hourly_rate


def build_variant_metrics(
    model_id: str,
    quant_level: str,
    is_lora: bool,
    results: list[CaseResult],
    model_memory_mb: float = 0.0,
    gpu_memory_mb: float | None = None,
    gpu_type: str = "A10G",
    backend: str = "ollama",
    custom_rates: dict[str, float] | None = None,
) -> VariantMetrics:
    """Aggregate per-case results into variant-level metrics."""
    latencies = [r.latency_ms for r in results]
    pcts = compute_latency_percentiles(latencies)
    tps = compute_tokens_per_second(results)
    cost = estimate_cost_per_1k(pcts["mean"], gpu_type, custom_rates)

    return VariantMetrics(
        model_id=model_id,
        quant_level=quant_level,
        is_lora=is_lora,
        backend=backend,
        latency_p50_ms=pcts["p50"],
        latency_p95_ms=pcts["p95"],
        latency_p99_ms=pcts["p99"],
        latency_mean_ms=pcts["mean"],
        tokens_per_second=tps,
        model_memory_mb=model_memory_mb,
        gpu_memory_mb=gpu_memory_mb,
        estimated_cost_per_1k_queries=cost,
    )

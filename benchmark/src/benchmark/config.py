"""Benchmark configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class BenchmarkConfig:
    """Configuration for the quantization & LoRA benchmark harness."""

    # Ollama connection
    ollama_base_url: str = "http://localhost:11434"

    # Model variants to benchmark (Ollama model tags).
    base_models: list[str] = field(default_factory=lambda: [
        "llama3:8b",                    # 8B Q4_0 (current production)
        "llama3:8b-instruct-q8_0",      # 8B Q8
        "llama3:8b-instruct-fp16",      # 8B FP16
        "llama3.2:3b",                  # 3B base (no LoRA)
    ])
    lora_models: list[str] = field(default_factory=lambda: [
        "llama3-kyb-lora:q4",           # 3B LoRA Q4_K_M
        "llama3-kyb-lora:q8",           # 3B LoRA Q8_0
        "llama3-kyb-lora:fp16",         # 3B LoRA FP16
    ])

    # Benchmark execution
    warmup_runs: int = 3
    benchmark_runs: int = 50
    goals: list[str] = field(default_factory=lambda: ["careers", "contact"])
    ollama_timeout: float = 30.0

    # Paths
    golden_data_dir: Path = Path("benchmark/golden_data")
    output_dir: Path = Path("benchmark/results")

    # MLflow
    mlflow_tracking_uri: str = "benchmark/mlflow_runs"
    mlflow_experiment: str = "kyb-quant-benchmark"

    # LoRA training hyperparameters
    lora_rank: int = 16
    lora_alpha: int = 32
    lora_dropout: float = 0.05
    lora_target_modules: str = "all-linear"
    lora_base_model: str = "meta-llama/Meta-Llama-3-8B"
    lora_epochs: int = 3
    lora_batch_size: int = 4
    lora_learning_rate: float = 2e-4

    # LoRA serving mode: "ollama" (GGUF) or "transformers" (native PEFT)
    lora_serving: str = "ollama"

    # Cost estimation: hourly rates for GPU instances (USD)
    gpu_cost_rates: dict[str, float] = field(default_factory=lambda: {
        "T4": 0.35,
        "A10G": 0.80,
        "A100": 2.21,
    })
    default_gpu: str = "A10G"


def load_config() -> BenchmarkConfig:
    """Build BenchmarkConfig from environment variable overrides."""
    cfg = BenchmarkConfig()

    if v := os.getenv("BENCHMARK_OLLAMA_BASE_URL"):
        cfg.ollama_base_url = v
    if v := os.getenv("OLLAMA_BASE_URL"):
        cfg.ollama_base_url = v
    if v := os.getenv("BENCHMARK_BASE_MODELS"):
        cfg.base_models = [m.strip() for m in v.split(",") if m.strip()]
    if v := os.getenv("BENCHMARK_LORA_MODELS"):
        cfg.lora_models = [m.strip() for m in v.split(",") if m.strip()]
    if v := os.getenv("BENCHMARK_WARMUP_RUNS"):
        cfg.warmup_runs = int(v)
    if v := os.getenv("BENCHMARK_RUNS"):
        cfg.benchmark_runs = int(v)
    if v := os.getenv("BENCHMARK_OLLAMA_TIMEOUT"):
        cfg.ollama_timeout = float(v)
    if v := os.getenv("BENCHMARK_GOLDEN_DATA_DIR"):
        cfg.golden_data_dir = Path(v)
    if v := os.getenv("BENCHMARK_OUTPUT_DIR"):
        cfg.output_dir = Path(v)
    if v := os.getenv("BENCHMARK_MLFLOW_URI"):
        cfg.mlflow_tracking_uri = v
    if v := os.getenv("BENCHMARK_MLFLOW_EXPERIMENT"):
        cfg.mlflow_experiment = v
    if v := os.getenv("BENCHMARK_LORA_RANK"):
        cfg.lora_rank = int(v)
    if v := os.getenv("BENCHMARK_LORA_ALPHA"):
        cfg.lora_alpha = int(v)
    if v := os.getenv("BENCHMARK_LORA_SERVING"):
        cfg.lora_serving = v
    if v := os.getenv("BENCHMARK_LORA_BASE_MODEL"):
        cfg.lora_base_model = v
    if v := os.getenv("BENCHMARK_DEFAULT_GPU"):
        cfg.default_gpu = v

    return cfg

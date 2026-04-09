# KYB Quantization & LoRA Benchmark Harness

Measures cost/quality/latency tradeoffs for running the KYB verification cascade's LLM classification layer at different quantization levels and with LoRA domain adaptation.

## Quick Start

```bash
# From the project root:
uv sync

# Pull the model variants you want to benchmark:
ollama pull llama3:8b
ollama pull llama3:8b-q8_0
ollama pull llama3:8b-q4_0

# Run the benchmark (all three quant levels, 50 runs per test case):
uv run python -m benchmark.cli run

# Or use the convenience script:
cd benchmark && uv run python run_benchmark.py
```

## Configuration

All settings can be overridden via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `BENCHMARK_OLLAMA_BASE_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_BASE_URL` | (fallback) | Also accepted for Ollama URL |
| `BENCHMARK_BASE_MODELS` | `llama3:8b,llama3:8b-q8_0,llama3:8b-q4_0` | Comma-separated model tags |
| `BENCHMARK_LORA_MODELS` | `llama3-kyb-lora:8b,...` | LoRA model tags (auto-skipped if unavailable) |
| `BENCHMARK_RUNS` | `50` | Benchmark runs per test case |
| `BENCHMARK_WARMUP_RUNS` | `3` | Warmup runs before benchmarking |
| `BENCHMARK_OUTPUT_DIR` | `benchmark/results` | Results output directory |
| `BENCHMARK_MLFLOW_URI` | `benchmark/mlflow_runs` | MLflow tracking URI |
| `BENCHMARK_DEFAULT_GPU` | `A10G` | GPU type for cost estimation |

## CLI Commands

```bash
# Run the full benchmark:
uv run python -m benchmark.cli run

# Benchmark specific models only:
uv run python -m benchmark.cli run -m llama3:8b -m llama3:8b-q4_0

# Fewer runs for quick testing:
uv run python -m benchmark.cli run --runs 5

# Skip LoRA variants:
uv run python -m benchmark.cli run --skip-lora

# Regenerate reports from existing results:
uv run python -m benchmark.cli report

# Generate JSONL training data from golden test set:
uv run python -m benchmark.cli generate-training-data

# Train a LoRA adapter (requires: uv sync --extra lora):
uv run python -m benchmark.cli train \
    --base-model meta-llama/Meta-Llama-3-8B \
    --train-data benchmark/golden_data/training.jsonl

# Merge LoRA adapter and register with Ollama:
uv run python -m benchmark.cli merge \
    --adapter benchmark/lora_adapters/adapter \
    --base-model meta-llama/Meta-Llama-3-8B
```

## Outputs

After `python -m benchmark.cli run`:

| File | Description |
|------|-------------|
| `results/comparison_report.json` | Machine-readable results for all variants |
| `results/comparison_report.md` | Markdown table comparing accuracy, latency, memory, cost |
| `results/accuracy_vs_cost.png` | Scatter plot of accuracy vs cost per 1K queries |
| `results/latency_distributions.png` | Box plots of latency distributions |
| `results/memory_comparison.png` | Bar chart of GPU memory per variant |
| `results/confusion_matrices.png` | Confusion matrix breakdown per variant |
| `results/raw_*.json` | Per-variant raw results for deeper analysis |

MLflow experiments are logged to `benchmark/mlflow_runs/`. View with:
```bash
mlflow ui --backend-store-uri benchmark/mlflow_runs
```

## Golden Test Set

Test cases live in `golden_data/element_pick_*.json`. Each case includes:
- Pre-extracted page elements (no live scraping needed)
- Expected correct pick index (or `null` for NONE)
- Difficulty rating (easy/medium/hard)

To add your own test cases, follow the schema in `golden_data/schema.json`. The benchmark uses the same prompt-building and response-parsing logic as the production verifier, ensuring results reflect real-world performance.

## Interpreting Results

- **Accuracy**: Fraction of test cases where the model picks the correct element (or correctly returns NONE).
- **Latency P50/P95/P99**: Percentile response times. P50 represents typical performance; P95/P99 represent tail latency.
- **Memory**: Model VRAM footprint from Ollama's `/api/ps` endpoint.
- **Cost per 1K**: Estimated cloud cost based on GPU-hours at the configured GPU type's hourly rate.
- **Pareto-optimal**: Variants that aren't dominated by any other variant on all three axes (accuracy, latency, cost). These represent the best tradeoff options.

## LoRA Fine-Tuning

The LoRA scaffold requires additional dependencies:

```bash
uv sync --extra lora
```

This installs PyTorch, Transformers, PEFT, bitsandbytes, and related libraries (~5GB). The workflow is:

1. **Generate training data**: `benchmark.cli generate-training-data` converts golden test cases to JSONL
2. **Populate with real examples**: Add domain-specific KYB verification examples to the JSONL
3. **Train**: `benchmark.cli train` runs PEFT LoRA fine-tuning with MLflow tracking
4. **Merge**: `benchmark.cli merge` merges the adapter into base weights, exports GGUF, and registers with Ollama
5. **Benchmark**: Re-run `benchmark.cli run` to include the LoRA variants

## Integration with Verifier

The benchmark integrates with the existing KYB verifier cascade via two environment variables:

```bash
# Select quantization level for the verifier's LLM layer:
export VERIFIER_QUANT_LEVEL=q4_0  # fp16, q8_0, q4_0, or "default"

# Toggle LoRA adapter:
export VERIFIER_USE_LORA=true
```

These modify the Ollama model tag used by `_get_ollama_model()` in the LangGraph nodes. When unset, behavior is identical to before.

# LoRA Fine-Tuning from Cascade Signals

Generates domain-specific training data from the KYB verification cascade's own high-confidence outputs, trains a LoRA adapter, and evaluates whether it improves accuracy on the false-pick failure mode.

## Pipeline

```
1. capture    → Run cascade against companies, capture training signals
2. prepare    → Filter by confidence, generate JSONL + edge cases
3. train      → LoRA fine-tuning (requires GPU + optional deps)
4. merge      → Export GGUF, register with Ollama
5. evaluate   → Benchmark base vs LoRA variants
```

## Quick Start

```bash
# From project root:
uv sync

# Generate company list from database:
uv run python -m lora.cli generate-company-list

# Run cascade capture (requires Ollama running):
uv run python -m lora.cli capture -c lora/company_list.json

# Filter and format training data:
uv run python -m lora.cli prepare -i lora/data/captured.jsonl

# Train LoRA adapter (requires: uv sync --extra lora in benchmark/):
uv run python -m lora.cli train -t lora/data/training.jsonl

# Merge and register with Ollama:
uv run python -m lora.cli merge --adapter lora/adapters/kyb-v1/adapter

# Evaluate all 6 variants:
uv run python -m lora.cli evaluate --edge-cases lora/data/edge_cases.json
```

## Confidence Gating

Training data quality comes from the cascade's built-in confidence signals:

| Source | ATS Detected | Label | Use |
|--------|-------------|-------|-----|
| DOM | any | high-confidence pick | Training |
| LLM/Vision | yes | high-confidence pick | Training |
| LLM/Vision | no | low-confidence pick | Edge case evaluation |
| Probe | any | LLM missed it | Training (NONE correction) |
| None | N/A | high-confidence NONE | Training |

The probe cases are the most valuable: the LLM said NONE but a careers page actually exists. These directly address the 8% false-pick error rate.

## NONE Oversampling

The `prepare` step oversamples NONE examples by 2x (configurable) to combat the false-pick bias observed in the quantization benchmark. This biases the training distribution toward teaching the model when NOT to pick.

## Output Files

After `prepare`:
- `lora/data/training.jsonl` — JSONL training data for `train_lora()`
- `lora/data/edge_cases.json` — Low-confidence cases for benchmark evaluation
- `lora/data/generation_stats.json` — Capture and labeling statistics

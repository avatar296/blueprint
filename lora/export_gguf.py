#!/usr/bin/env python3
"""Export saved QLoRA adapter to GGUF and register with Ollama.

Loads the adapter from lora/adapters/kyb-v1/adapter/ and runs
Unsloth's merge + GGUF conversion pipeline.

Usage:
    cd ~/blueprint
    uv run python -u lora/export_gguf.py
"""

import subprocess
import sys
from pathlib import Path

from unsloth import FastLanguageModel

# ── Config ──────────────────────────────────────────────────────────
ADAPTER_DIR = "lora/adapters/kyb-v1/adapter"
OUTPUT_DIR = "lora/adapters/kyb-v1"
MAX_SEQ_LEN = 1280

# Llama 3.2 Instruct chat template for Ollama Modelfiles.
LLAMA32_TEMPLATE = r'''"""<|start_header_id|>system<|end_header_id|>

Cutting Knowledge Date: December 2023

{{ if .System }}{{ .System }}
{{- end }}<|eot_id|>
{{- range $i, $_ := .Messages }}
{{- $last := eq (len (slice $.Messages $i)) 1 }}
{{- if eq .Role "user" }}<|start_header_id|>user<|end_header_id|>

{{ .Content }}<|eot_id|>{{ if $last }}<|start_header_id|>assistant<|end_header_id|>

{{ end }}
{{- else if eq .Role "assistant" }}<|start_header_id|>assistant<|end_header_id|>

{{ .Content }}{{ if not $last }}<|eot_id|>{{ end }}
{{- end }}
{{- end }}"""'''

QUANT_LEVELS = [("f16", "fp16"), ("q8_0", "q8"), ("q4_k_m", "q4")]


# ── Load adapter ───────────────────────────────────────────────────
print("Loading adapter from saved checkpoint...", flush=True)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=ADAPTER_DIR,
    max_seq_length=MAX_SEQ_LEN,
    load_in_4bit=True,
)

# ── Export GGUF at 3 quantization levels ───────────────────────────
output_path = Path(OUTPUT_DIR)
gguf_dir = str(output_path / "gguf")

print("\nExporting GGUF models via Unsloth...", flush=True)
for quant, tag_suffix in QUANT_LEVELS:
    print(f"\n  Exporting {quant}...", flush=True)
    model.save_pretrained_gguf(
        gguf_dir,
        tokenizer,
        quantization_method=quant,
    )

    # Find the exported GGUF file and register with Ollama.
    gguf_files = list(Path(gguf_dir).glob("*.gguf"))
    if not gguf_files:
        print(f"  WARNING: No .gguf files found after {quant} export", flush=True)
        continue

    latest = max(gguf_files, key=lambda f: f.stat().st_mtime)
    tag = f"llama3-kyb-lora:{tag_suffix}"

    # Write Modelfile with chat template + stop tokens.
    modelfile = output_path / f"Modelfile.{quant}"
    modelfile.write_text(
        f"FROM {latest.resolve()}\n"
        f"TEMPLATE {LLAMA32_TEMPLATE}\n"
        "PARAMETER stop <|start_header_id|>\n"
        "PARAMETER stop <|end_header_id|>\n"
        "PARAMETER stop <|eot_id|>\n"
    )

    result = subprocess.run(
        ["ollama", "create", tag, "-f", str(modelfile)],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        print(f"  Registered with Ollama: {tag}", flush=True)
    else:
        print(f"  Ollama registration failed for {tag}: {result.stderr}", flush=True)

print("\nDONE. Models registered with Ollama:", flush=True)
for _, tag_suffix in QUANT_LEVELS:
    print(f"  llama3-kyb-lora:{tag_suffix}", flush=True)

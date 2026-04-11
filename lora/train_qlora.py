#!/usr/bin/env python3
"""QLoRA training via Unsloth for KYB element-classification adapter.

Usage:
    cd ~/blueprint
    uv run python -u lora/train_qlora.py

Requires:
    - HF_TOKEN in .env
    - GPU with 8GB+ VRAM
    - unsloth installed: uv pip install "unsloth[cu124-torch2.6]"
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()


from unsloth import FastLanguageModel
from datasets import load_dataset
from trl import SFTTrainer
from transformers import TrainingArguments, TrainerCallback

# ── Config ──────────────────────────────────────────────────────────
BASE_MODEL = "unsloth/Llama-3.2-3B-Instruct"
TRAIN_DATA = "lora/data/training.jsonl"
OUTPUT_DIR = "lora/adapters/kyb-v1"
MAX_SEQ_LEN = 1280
LORA_RANK = 16
LORA_ALPHA = 32
LORA_DROPOUT = 0.05
EPOCHS = 3
BATCH_SIZE = 1
GRAD_ACCUM = 8
LR = 2e-4


# ── Progress callback ──────────────────────────────────────────────
class PrintProgress(TrainerCallback):
    def __init__(self):
        self.t0 = None
        self.total = None

    def on_train_begin(self, args, state, control, **kwargs):
        self.t0 = time.time()
        self.total = state.max_steps
        print(f"\n{'='*60}", flush=True)
        print(f"Training: {self.total} steps, {EPOCHS} epochs", flush=True)
        print(f"Effective batch: {BATCH_SIZE} x {GRAD_ACCUM} = {BATCH_SIZE * GRAD_ACCUM}", flush=True)
        print(f"{'='*60}\n", flush=True)

    def on_log(self, args, state, control, logs=None, **kwargs):
        if logs and "loss" in logs:
            elapsed = time.time() - self.t0
            step = state.global_step
            pct = step / self.total * 100
            sps = elapsed / step if step > 0 else 0
            eta = sps * (self.total - step)
            print(
                f"  Step {step:>4}/{self.total} ({pct:5.1f}%) | "
                f"loss={logs['loss']:.4f} | "
                f"lr={logs.get('learning_rate', 0):.2e} | "
                f"{elapsed/60:.1f}m elapsed | {eta/60:.1f}m remaining",
                flush=True,
            )

    def on_epoch_end(self, args, state, control, **kwargs):
        print(f"\n  >>> Epoch {int(state.epoch)} done ({(time.time()-self.t0)/60:.1f}m)\n", flush=True)

    def on_train_end(self, args, state, control, **kwargs):
        print(f"\n{'='*60}", flush=True)
        print(f"Training complete in {(time.time()-self.t0)/60:.1f} minutes", flush=True)
        print(f"{'='*60}\n", flush=True)


# ── Load model ──────────────────────────────────────────────────────
print("Loading model...", flush=True)
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name=BASE_MODEL,
    max_seq_length=MAX_SEQ_LEN,
    load_in_4bit=True,
)

# ── Apply LoRA ──────────────────────────────────────────────────────
model = FastLanguageModel.get_peft_model(
    model,
    r=LORA_RANK,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    target_modules=[
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    bias="none",
    use_gradient_checkpointing="unsloth",
)

# ── Load and format data ────────────────────────────────────────────
print(f"Loading training data: {TRAIN_DATA}", flush=True)
dataset = load_dataset("json", data_files=TRAIN_DATA, split="train")


def format_chat(example):
    """Convert messages list to Llama 3 chat template."""
    messages = example["messages"]
    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    return {"text": text}


dataset = dataset.map(format_chat)
print(f"Formatted {len(dataset)} examples", flush=True)

# ── Train ───────────────────────────────────────────────────────────
output_path = Path(OUTPUT_DIR)
output_path.mkdir(parents=True, exist_ok=True)

trainer = SFTTrainer(
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
    args=TrainingArguments(
        output_dir=str(output_path / "checkpoints"),
        num_train_epochs=EPOCHS,
        per_device_train_batch_size=BATCH_SIZE,
        gradient_accumulation_steps=GRAD_ACCUM,
        learning_rate=LR,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=1,
        logging_first_step=True,
        save_strategy="epoch",
        fp16=False,
        bf16=True,
        optim="adamw_8bit",
        seed=42,
        report_to="none",
        disable_tqdm=True,
    ),
    callbacks=[PrintProgress()],
)

print("\nStarting training...", flush=True)
trainer.train()

# ── Save adapter ────────────────────────────────────────────────────
adapter_path = str(output_path / "adapter")
model.save_pretrained(adapter_path)
tokenizer.save_pretrained(adapter_path)
print(f"\nAdapter saved to {adapter_path}", flush=True)

# ── Export GGUF at 3 quantization levels ────────────────────────────
print("\nExporting GGUF models...", flush=True)
gguf_dir = str(output_path / "gguf")

for quant, tag_suffix in [("f16", "fp16"), ("q8_0", "q8"), ("q4_k_m", "q4")]:
    print(f"  Exporting {quant}...", flush=True)
    model.save_pretrained_gguf(
        gguf_dir,
        tokenizer,
        quantization_method=quant,
    )
    # Find the exported file and register with Ollama
    gguf_files = list(Path(gguf_dir).glob("*.gguf"))
    if gguf_files:
        latest = max(gguf_files, key=lambda f: f.stat().st_mtime)
        tag = f"llama3-kyb-lora:{tag_suffix}"
        modelfile = output_path / f"Modelfile.{quant}"
        # Include Llama 3.2 Instruct chat template + stop tokens.
        modelfile.write_text(
            f"FROM {latest.resolve()}\n"
            'TEMPLATE """<|start_header_id|>system<|end_header_id|>\n'
            "\n"
            "Cutting Knowledge Date: December 2023\n"
            "\n"
            "{{ if .System }}{{ .System }}\n"
            "{{- end }}<|eot_id|>\n"
            "{{- range $i, $_ := .Messages }}\n"
            '{{- $last := eq (len (slice $.Messages $i)) 1 }}\n'
            '{{- if eq .Role "user" }}<|start_header_id|>user<|end_header_id|>\n'
            "\n"
            "{{ .Content }}<|eot_id|>{{ if $last }}<|start_header_id|>assistant<|end_header_id|>\n"
            "\n"
            "{{ end }}\n"
            '{{- else if eq .Role "assistant" }}<|start_header_id|>assistant<|end_header_id|>\n'
            "\n"
            '{{ .Content }}{{ if not $last }}<|eot_id|>{{ end }}\n'
            "{{- end }}\n"
            '{{- end }}"""\n'
            "PARAMETER stop <|start_header_id|>\n"
            "PARAMETER stop <|end_header_id|>\n"
            "PARAMETER stop <|eot_id|>\n"
        )
        import subprocess
        result = subprocess.run(
            ["ollama", "create", tag, "-f", str(modelfile)],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            print(f"  Registered with Ollama: {tag}", flush=True)
        else:
            print(f"  Ollama registration failed for {tag}: {result.stderr}", flush=True)

print("\nDONE. Models registered with Ollama:", flush=True)
print("  llama3-kyb-lora:fp16", flush=True)
print("  llama3-kyb-lora:q8", flush=True)
print("  llama3-kyb-lora:q4", flush=True)

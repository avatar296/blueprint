"""LoRA fine-tuning scaffold using PEFT / HuggingFace Transformers.

Requires optional ``[lora]`` dependencies:
    uv sync --extra lora
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def create_lora_config(
    rank: int = 16,
    alpha: int = 32,
    dropout: float = 0.05,
    target_modules: str = "all-linear",
):
    """Create a PEFT LoRA configuration.

    Default hyperparameters target KYB element-classification fine-tuning:
    rank=16, alpha=32, dropout=0.05, all linear layers.
    """
    from peft import LoraConfig, TaskType

    return LoraConfig(
        task_type=TaskType.CAUSAL_LM,
        r=rank,
        lora_alpha=alpha,
        lora_dropout=dropout,
        target_modules=target_modules,
        bias="none",
    )


def train_lora(
    base_model: str,
    train_data: str,
    output_dir: str,
    config=None,
    *,
    qlora: bool = False,
    gradient_accumulation_steps: int = 1,
) -> str:
    """Fine-tune a LoRA adapter on KYB element-classification data.

    Args:
        base_model: HuggingFace model ID (e.g. 'meta-llama/Meta-Llama-3-8B-Instruct').
        train_data: Path to JSONL training file.
        output_dir: Directory to save the LoRA adapter.
        config: Optional BenchmarkConfig for hyperparameter overrides.
        qlora: If True, load base model in 4-bit via BitsAndBytesConfig
            (QLoRA). Fits Llama 3 8B on consumer GPUs with 8GB VRAM.
        gradient_accumulation_steps: Accumulate gradients over N steps
            before updating. Use with batch_size=1 for memory-constrained
            GPUs (effective batch = batch_size × accumulation).

    Returns:
        Path to the saved adapter directory.
    """
    import torch
    from datasets import load_dataset
    from peft import get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        DataCollatorForLanguageModeling,
        Trainer,
        TrainingArguments,
    )

    # Resolve hyperparameters.
    rank = config.lora_rank if config else 16
    alpha = config.lora_alpha if config else 32
    dropout = config.lora_dropout if config else 0.05
    epochs = config.lora_epochs if config else 3
    batch_size = config.lora_batch_size if config else 4
    lr = config.lora_learning_rate if config else 2e-4

    log.info("Loading base model: %s (qlora=%s)", base_model, qlora)
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # Model loading: QLoRA (4-bit) or full precision.
    if qlora:
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.float16,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            quantization_config=bnb_config,
            device_map="auto",
        )
        model = prepare_model_for_kbit_training(model)
        log.info("Loaded in 4-bit QLoRA mode (NF4 + double quant)")
    else:
        model = AutoModelForCausalLM.from_pretrained(
            base_model,
            device_map="auto",
            torch_dtype="auto",
        )

    # Apply LoRA.
    lora_config = create_lora_config(rank=rank, alpha=alpha, dropout=dropout)
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Load training data.
    log.info("Loading training data: %s", train_data)
    dataset = load_dataset("json", data_files=train_data, split="train")

    def _tokenize(example):
        """Convert chat messages to a single text sequence."""
        messages = example.get("messages", [])
        text_parts = []
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            text_parts.append(f"<|{role}|>\n{content}")
        text_parts.append("<|assistant|>")
        text = "\n".join(text_parts)
        return tokenizer(text, truncation=True, max_length=1280)

    tokenized = dataset.map(_tokenize, remove_columns=dataset.column_names)

    # Training arguments.
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_path / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        gradient_accumulation_steps=gradient_accumulation_steps,
        learning_rate=lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=1,
        logging_first_step=True,
        save_strategy="epoch",
        fp16=True,
        optim="paged_adamw_8bit" if qlora else "adamw_torch",
        report_to=["none"],
        disable_tqdm=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False, pad_to_multiple_of=8),
    )

    eff_batch = batch_size * gradient_accumulation_steps
    log.info(
        "Starting %s training: epochs=%d, batch=%d, grad_accum=%d (eff_batch=%d), lr=%s",
        "QLoRA" if qlora else "LoRA", epochs, batch_size,
        gradient_accumulation_steps, eff_batch, lr,
    )
    trainer.train()

    # Save adapter (not the full model).
    adapter_path = str(output_path / "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    log.info("LoRA adapter saved to: %s", adapter_path)

    return adapter_path

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
) -> str:
    """Fine-tune a LoRA adapter on KYB element-classification data.

    Args:
        base_model: HuggingFace model ID (e.g. 'meta-llama/Meta-Llama-3-8B').
        train_data: Path to JSONL training file.
        output_dir: Directory to save the LoRA adapter.
        config: Optional BenchmarkConfig for hyperparameter overrides.

    Returns:
        Path to the saved adapter directory.
    """
    from datasets import load_dataset
    from peft import get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        TrainingArguments,
        Trainer,
        DataCollatorForLanguageModeling,
    )

    # Resolve hyperparameters.
    rank = config.lora_rank if config else 16
    alpha = config.lora_alpha if config else 32
    dropout = config.lora_dropout if config else 0.05
    epochs = config.lora_epochs if config else 3
    batch_size = config.lora_batch_size if config else 4
    lr = config.lora_learning_rate if config else 2e-4

    log.info("Loading base model: %s", base_model)
    tokenizer = AutoTokenizer.from_pretrained(base_model)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

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
        return tokenizer(text, truncation=True, max_length=2048, padding="max_length")

    tokenized = dataset.map(_tokenize, remove_columns=dataset.column_names)

    # Training arguments.
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_path / "checkpoints"),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        learning_rate=lr,
        warmup_ratio=0.1,
        weight_decay=0.01,
        logging_steps=10,
        save_strategy="epoch",
        fp16=True,
        report_to=["mlflow"],
        run_name="kyb-lora-training",
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=tokenized,
        data_collator=DataCollatorForLanguageModeling(tokenizer, mlm=False),
    )

    log.info("Starting LoRA training: epochs=%d, batch=%d, lr=%s", epochs, batch_size, lr)
    trainer.train()

    # Save adapter (not the full model).
    adapter_path = str(output_path / "adapter")
    model.save_pretrained(adapter_path)
    tokenizer.save_pretrained(adapter_path)
    log.info("LoRA adapter saved to: %s", adapter_path)

    return adapter_path

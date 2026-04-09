"""HuggingFace Transformers backend for native LoRA serving.

Requires optional ``[lora]`` dependencies:
    uv sync --extra lora

This backend is for LoRA development iteration (no GGUF conversion step).
Results are tagged with ``backend=transformers`` to distinguish from the
production Ollama path.
"""

from __future__ import annotations

import logging
import time

from .base import InvokeResult

log = logging.getLogger(__name__)


class TransformersBackend:
    """Serve a LoRA-adapted model natively via HuggingFace + PEFT.

    Tradeoffs vs OllamaBackend:
        + No GGUF conversion step — faster iteration during LoRA development
        + Direct adapter hot-swap
        - Different tokenization/inference path than production
        - Requires torch + CUDA (~5GB extra deps)
    """

    def __init__(
        self,
        base_model: str,
        adapter_path: str | None = None,
        quant_config: str = "fp16",
    ) -> None:
        from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
        import torch

        self._base_model_name = base_model
        self._adapter_path = adapter_path
        self._quant_config_name = quant_config

        # Build quantization config.
        bnb_config = None
        torch_dtype = torch.float16
        if quant_config == "int8":
            bnb_config = BitsAndBytesConfig(load_in_8bit=True)
        elif quant_config == "int4":
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
            )

        log.info("Loading model %s (quant=%s)", base_model, quant_config)
        self._tokenizer = AutoTokenizer.from_pretrained(base_model)
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token

        self._model = AutoModelForCausalLM.from_pretrained(
            base_model,
            quantization_config=bnb_config,
            torch_dtype=torch_dtype,
            device_map="auto",
        )

        if adapter_path:
            from peft import PeftModel

            log.info("Loading LoRA adapter from %s", adapter_path)
            self._model = PeftModel.from_pretrained(self._model, adapter_path)

        self._model.eval()

    @property
    def model_id(self) -> str:
        name = self._base_model_name.split("/")[-1]
        if self._adapter_path:
            name += "-lora"
        return f"{name}-{self._quant_config_name}"

    @property
    def quant_level(self) -> str:
        return {
            "fp16": "fp16",
            "int8": "q8_0",
            "int4": "q4_0",
        }.get(self._quant_config_name, self._quant_config_name)

    @property
    def is_lora(self) -> bool:
        return self._adapter_path is not None

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 50,
    ) -> InvokeResult:
        """Run inference through HuggingFace model."""
        import torch

        prompt = f"<|system|>\n{system_prompt}\n<|user|>\n{user_prompt}\n<|assistant|>\n"
        inputs = self._tokenizer(prompt, return_tensors="pt").to(self._model.device)
        prompt_tokens = inputs["input_ids"].shape[1]

        t0 = time.perf_counter_ns()

        with torch.no_grad():
            outputs = self._model.generate(
                **inputs,
                max_new_tokens=max_tokens,
                temperature=temperature if temperature > 0 else None,
                do_sample=temperature > 0,
                pad_token_id=self._tokenizer.pad_token_id,
            )

        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000

        # Decode only the generated tokens.
        generated = outputs[0][prompt_tokens:]
        content = self._tokenizer.decode(generated, skip_special_tokens=True).strip()
        completion_tokens = len(generated)

        return InvokeResult(
            content=content,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    async def get_memory_mb(self) -> float:
        """Estimate model memory from parameter count and dtype."""
        total_bytes = 0
        for param in self._model.parameters():
            total_bytes += param.nelement() * param.element_size()
        return total_bytes / (1024 * 1024)

    async def health_check(self) -> bool:
        return True

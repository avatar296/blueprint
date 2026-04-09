"""Abstract model backend protocol and shared data structures."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class InvokeResult:
    """Result from a single model invocation."""

    content: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@runtime_checkable
class ModelBackend(Protocol):
    """Uniform interface for model serving backends (Ollama, Transformers)."""

    @property
    def model_id(self) -> str:
        """Full model identifier (e.g. 'llama3:8b-q4_0')."""
        ...

    @property
    def quant_level(self) -> str:
        """Quantization level: 'fp16', 'q8_0', 'q4_0'."""
        ...

    @property
    def is_lora(self) -> bool:
        """Whether this backend uses a LoRA-adapted model."""
        ...

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 50,
    ) -> InvokeResult:
        """Run inference and return result with timing metadata."""
        ...

    async def get_memory_mb(self) -> float:
        """Return model memory footprint in MB."""
        ...

    async def health_check(self) -> bool:
        """Return True if the backend is ready to serve."""
        ...

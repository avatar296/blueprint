"""Ollama model backend — wraps ChatOllama with timing and memory instrumentation."""

from __future__ import annotations

import logging
import time

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from .base import InvokeResult

log = logging.getLogger(__name__)

# Maps model tag suffixes to canonical quant level names.
_QUANT_MAP: dict[str, str] = {
    "q4_0": "q4_0",
    "q4_1": "q4_1",
    "q4_k_m": "q4_k_m",
    "q5_0": "q5_0",
    "q5_k_m": "q5_k_m",
    "q8_0": "q8_0",
}


def _parse_quant(model_tag: str) -> str:
    """Extract quantization level from an Ollama model tag.

    Falls back to tag parsing if the API isn't available.

    Examples:
        'llama3:8b-q4_0'  -> 'q4_0'
        'llama3:8b-q8_0'  -> 'q8_0'
        'llama3:8b'       -> 'fp16' (fallback; use _query_quant for truth)
    """
    tag_part = model_tag.split(":")[-1] if ":" in model_tag else model_tag
    for suffix, level in _QUANT_MAP.items():
        if suffix in tag_part.lower():
            return level
    return "fp16"


def _query_quant(model_tag: str, base_url: str) -> str | None:
    """Query Ollama /api/show for the actual quantization level."""
    try:
        import httpx as _httpx

        resp = _httpx.post(
            f"{base_url}/api/show",
            json={"name": model_tag},
            timeout=5.0,
        )
        resp.raise_for_status()
        level = resp.json().get("details", {}).get("quantization_level", "")
        if level:
            return level.lower()
    except Exception:
        pass
    return None


class OllamaBackend:
    """Model backend using Ollama for inference.

    Mirrors the ChatOllama invocation pattern from
    ``verifier.graph.nodes._langchain_pick_element``.
    """

    def __init__(
        self,
        model_tag: str,
        base_url: str = "http://localhost:11434",
        *,
        is_lora: bool = False,
        timeout: float = 30.0,
    ) -> None:
        self._model_tag = model_tag
        self._base_url = base_url.rstrip("/")
        self._is_lora = is_lora
        self._timeout = timeout
        # Query Ollama for the real quantization level, fall back to tag parsing.
        api_quant = _query_quant(model_tag, self._base_url)
        self._quant = api_quant if api_quant else _parse_quant(model_tag)

    @property
    def model_id(self) -> str:
        return self._model_tag

    @property
    def quant_level(self) -> str:
        return self._quant

    @property
    def is_lora(self) -> bool:
        return self._is_lora

    async def invoke(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.0,
        max_tokens: int = 50,
    ) -> InvokeResult:
        """Run inference through ChatOllama and capture timing."""
        llm = ChatOllama(
            model=self._model_tag,
            base_url=self._base_url,
            temperature=temperature,
            num_predict=max_tokens,
            timeout=self._timeout,
        )

        t0 = time.perf_counter_ns()
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ])
        latency_ms = (time.perf_counter_ns() - t0) / 1_000_000

        # Extract token counts from response metadata when available.
        meta = getattr(response, "response_metadata", {}) or {}
        prompt_tokens = meta.get("prompt_eval_count", 0)
        completion_tokens = meta.get("eval_count", 0)

        return InvokeResult(
            content=response.content,
            latency_ms=latency_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        )

    async def get_memory_mb(self) -> float:
        """Query Ollama /api/ps for VRAM used by the loaded model."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/ps")
                resp.raise_for_status()
                data = resp.json()

            for model in data.get("models", []):
                if model.get("name", "").startswith(self._model_tag.split(":")[0]):
                    size_bytes = model.get("size", 0)
                    return size_bytes / (1024 * 1024)

            log.debug("Model %s not found in /api/ps response", self._model_tag)
            return 0.0
        except Exception:
            log.debug("Failed to query Ollama /api/ps", exc_info=True)
            return 0.0

    async def health_check(self) -> bool:
        """Check model is available in Ollama."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                resp.raise_for_status()
                data = resp.json()

            available = {m["name"] for m in data.get("models", [])}
            # Check both exact match and prefix match (ollama may append :latest).
            if self._model_tag in available:
                return True
            for name in available:
                if name.startswith(self._model_tag):
                    return True

            log.warning(
                "Model %s not found in Ollama. Available: %s",
                self._model_tag,
                ", ".join(sorted(available)),
            )
            return False
        except Exception:
            log.warning("Cannot reach Ollama at %s", self._base_url, exc_info=True)
            return False

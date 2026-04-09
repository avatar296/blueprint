"""Verifier configuration loaded from environment variables."""

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("verifier.config")


@dataclass
class VerifierConfig:
    batch_size: int = 500
    website_concurrency: int = 50
    ddg_daily_limit: int = 1000
    sec_concurrency: int = 10
    discovery_concurrency: int = 5
    ollama_base_url: str | None = None
    ollama_model: str = "llama3"
    ollama_timeout: float = 10.0
    ollama_vision_model: str | None = None
    ollama_vision_timeout: float = 15.0
    reverify_days: int = 30
    idle_sleep_seconds: int = 30
    use_langgraph: bool = False
    quant_level: str = "default"
    use_lora: bool = False


def load_config() -> VerifierConfig:
    """Build VerifierConfig from env var overrides."""
    cfg = VerifierConfig()

    if v := os.getenv("VERIFIER_BATCH_SIZE"):
        cfg.batch_size = int(v)
    if v := os.getenv("VERIFIER_WEBSITE_CONCURRENCY"):
        cfg.website_concurrency = int(v)
    if v := os.getenv("VERIFIER_DDG_DAILY_LIMIT"):
        cfg.ddg_daily_limit = int(v)
    if v := os.getenv("VERIFIER_SEC_CONCURRENCY"):
        cfg.sec_concurrency = int(v)
    if v := os.getenv("VERIFIER_DISCOVERY_CONCURRENCY"):
        cfg.discovery_concurrency = int(v)
    if v := os.getenv("OLLAMA_BASE_URL"):
        cfg.ollama_base_url = v
    if v := os.getenv("VERIFIER_LLM_MODEL"):
        cfg.ollama_model = v
    if v := os.getenv("VERIFIER_LLM_TIMEOUT"):
        cfg.ollama_timeout = float(v)
    if v := os.getenv("VERIFIER_VISION_MODEL"):
        cfg.ollama_vision_model = v
    if v := os.getenv("VERIFIER_VISION_TIMEOUT"):
        cfg.ollama_vision_timeout = float(v)
    if v := os.getenv("VERIFIER_REVERIFY_DAYS"):
        cfg.reverify_days = int(v)
    if v := os.getenv("VERIFIER_IDLE_SLEEP_SECONDS"):
        cfg.idle_sleep_seconds = int(v)
    if os.getenv("VERIFIER_USE_LANGGRAPH", "").lower() in ("1", "true", "yes"):
        cfg.use_langgraph = True
    if v := os.getenv("VERIFIER_QUANT_LEVEL"):
        cfg.quant_level = v
    if os.getenv("VERIFIER_USE_LORA", "").lower() in ("1", "true", "yes"):
        cfg.use_lora = True

    log.info(
        "Config: batch=%d, website_concurrency=%d, ddg_limit=%d, sec_concurrency=%d, discovery_concurrency=%d, ollama=%s, model=%s, vision_model=%s, reverify_days=%d, idle_sleep=%ds",
        cfg.batch_size,
        cfg.website_concurrency,
        cfg.ddg_daily_limit,
        cfg.sec_concurrency,
        cfg.discovery_concurrency,
        cfg.ollama_base_url or "disabled",
        cfg.ollama_model,
        cfg.ollama_vision_model or "disabled",
        cfg.reverify_days,
        cfg.idle_sleep_seconds,
    )
    if cfg.use_langgraph:
        log.info("LangGraph discovery cascade ENABLED")
    return cfg

"""Verifier service entrypoint — continuous runner for company signals."""

import logging
import os
import signal
import sys
import time

from common.db import get_pool

from verifier.config import load_config
from verifier.runner import run_verification

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# Silence noisy HTTP/search libraries
logging.getLogger("ddgs").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("primp").setLevel(logging.WARNING)
log = logging.getLogger("verifier")

_shutdown = False


def _handle_signal(signum, _frame):
    global _shutdown
    log.info("Received signal %d — shutting down gracefully", signum)
    _shutdown = True


def check_env() -> None:
    required = ["DATABASE_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def run_cycle(config) -> int:
    """Run one verification cycle. Returns total signals upserted."""
    log.info("=== Company verification ===")
    try:
        return run_verification(
            batch_size=config.batch_size,
            reverify_days=config.reverify_days,
            website_concurrency=config.website_concurrency,
            ddg_limit=config.ddg_daily_limit,
            sec_concurrency=config.sec_concurrency,
            discovery_concurrency=config.discovery_concurrency,
            ollama_base_url=config.ollama_base_url,
            ollama_model=config.ollama_model,
            ollama_timeout=config.ollama_timeout,
            ollama_vision_model=config.ollama_vision_model,
            ollama_vision_timeout=config.ollama_vision_timeout,
        )
    except Exception:
        log.error("Verification cycle failed", exc_info=True)
        return 0


def main() -> None:
    check_env()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    config = load_config()
    log.info("Verifier starting — continuous mode, idle backoff %ds", config.idle_sleep_seconds)

    get_pool()
    log.info("Database connection pool initialized")

    while not _shutdown:
        count = run_cycle(config)
        if count == 0:
            log.info("No work — sleeping %ds", config.idle_sleep_seconds)
            elapsed = 0
            while elapsed < config.idle_sleep_seconds and not _shutdown:
                time.sleep(1)
                elapsed += 1

    log.info("Verifier shutdown complete")


if __name__ == "__main__":
    main()

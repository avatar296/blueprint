"""Evaluator service entrypoint — scores jobs against the Master Profile."""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("evaluator")


def check_env() -> None:
    required = ["DATABASE_URL", "OLLAMA_BASE_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def main() -> None:
    check_env()
    interval = int(os.getenv("EVALUATOR_INTERVAL_MINUTES", "5")) * 60
    log.info("Evaluator starting — polling every %d minutes", interval // 60)

    while True:
        log.info("Evaluator cycle starting (not yet implemented)")
        # TODO: fetch unscored jobs from PostgreSQL
        # TODO: load /app/data/master_profile.json
        # TODO: score each JD via LangChain + Ollama
        # TODO: write fit_score + rationale back to DB
        time.sleep(interval)


if __name__ == "__main__":
    main()

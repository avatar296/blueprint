"""Scout service entrypoint — orchestrates company sourcing pipeline."""

import logging
import os
import signal
import sys
import time

from common.db import get_pool

from scout.config import load_config
from scout.sourcing_runner import run_sourcing

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("scout")

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


def run_cycle() -> int:
    """Run one sourcing cycle. Returns total records upserted."""
    config = load_config()

    log.info("=== Company sourcing ===")
    try:
        return run_sourcing(source_batch_limit=config.source_batch_limit)
    except Exception:
        log.error("Sourcing cycle failed", exc_info=True)
        return 0


def main() -> None:
    check_env()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    interval = int(os.getenv("SCOUT_INTERVAL_MINUTES", "60")) * 60
    log.info("Scout starting — sourcing cycle every %d min", interval // 60)

    # Eagerly initialize the DB pool to fail fast on bad credentials
    get_pool()
    log.info("Database connection pool initialized")

    while not _shutdown:
        log.info("Scout cycle starting")

        try:
            run_cycle()
        except Exception:
            log.error("Cycle failed unexpectedly", exc_info=True)

        # Interruptible sleep — check shutdown flag every 5 seconds
        elapsed = 0
        while elapsed < interval and not _shutdown:
            time.sleep(5)
            elapsed += 5

    log.info("Scout shutdown complete")


if __name__ == "__main__":
    main()

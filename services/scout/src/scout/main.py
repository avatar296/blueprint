"""Scout service entrypoint — polls job boards and stores listings."""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("scout")


def check_env() -> None:
    required = ["DATABASE_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def main() -> None:
    check_env()
    interval = int(os.getenv("SCOUT_INTERVAL_MINUTES", "60")) * 60
    log.info("Scout starting — polling every %d minutes", interval // 60)

    while True:
        log.info("Scout cycle starting (not yet implemented)")
        # TODO: scrape LinkedIn, Indeed, niche boards via Playwright
        # TODO: deduplicate and insert new listings into PostgreSQL
        time.sleep(interval)


if __name__ == "__main__":
    main()

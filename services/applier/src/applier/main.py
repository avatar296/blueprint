"""Applier service entrypoint — generates resumes and submits applications."""

import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("applier")


def check_env() -> None:
    required = ["DATABASE_URL"]
    missing = [v for v in required if not os.getenv(v)]
    if missing:
        log.error("Missing required env vars: %s", ", ".join(missing))
        sys.exit(1)


def main() -> None:
    check_env()
    log.info("Applier starting — waiting for approved jobs")

    while True:
        log.info("Applier cycle starting (not yet implemented)")
        # TODO: fetch approved jobs from PostgreSQL
        # TODO: load /app/data/master_profile.json
        # TODO: generate LaTeX resume via Jinja2 templates
        # TODO: compile to PDF
        # TODO: submit via Playwright on Workday/Lever
        time.sleep(300)


if __name__ == "__main__":
    main()

"""Scout configuration loaded from environment variables."""

import logging
import os
from dataclasses import dataclass

log = logging.getLogger("scout.config")


@dataclass
class ScoutConfig:
    # Sourcing batch limit (0 = unlimited)
    source_batch_limit: int = 0


def load_config() -> ScoutConfig:
    """Build ScoutConfig from env var overrides."""
    cfg = ScoutConfig()

    if env_batch := os.getenv("SCOUT_SOURCE_BATCH_LIMIT"):
        cfg.source_batch_limit = int(env_batch)

    log.info("Config: batch_limit=%s", cfg.source_batch_limit or "unlimited")
    return cfg

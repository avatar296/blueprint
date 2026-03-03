"""Scout configuration loaded from master_profile.json with env var overrides."""

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("scout.config")

_DEFAULT_ROLES = [
    "Principal Architect",
    "Staff Engineer",
    "Data Scientist",
]
_PROFILE_PATH = Path("/app/data/master_profile.json")


@dataclass
class ScoutConfig:
    roles: list[str] = field(default_factory=lambda: list(_DEFAULT_ROLES))
    max_age_days: int = 30

    # Sourcing batch limit (0 = unlimited)
    source_batch_limit: int = 0

    # Catalog filtering (applied to fetch_filtered_discoveries)
    min_employees: int | None = None
    max_employees: int | None = None
    founded_after: int | None = None  # year, e.g. 2000
    filter_states: list[str] = field(default_factory=list)
    filter_industries: list[str] = field(default_factory=list)


def load_config() -> ScoutConfig:
    """Build ScoutConfig from master_profile.json + env var overrides."""
    cfg = ScoutConfig()

    # Load from profile if available
    profile_path = Path(os.getenv("MASTER_PROFILE_PATH", str(_PROFILE_PATH)))
    if profile_path.exists():
        try:
            profile = json.loads(profile_path.read_text())
            header = profile.get("header", {})
            if roles := header.get("roles"):
                cfg.roles = roles
                log.info("Loaded %d roles from profile", len(roles))
        except (json.JSONDecodeError, KeyError, TypeError):
            log.warning("Failed to parse master_profile.json, using defaults")
    else:
        log.info("No master_profile.json found at %s, using defaults", profile_path)

    # Env var overrides
    if env_roles := os.getenv("SCOUT_ROLES"):
        cfg.roles = [r.strip() for r in env_roles.split(",") if r.strip()]

    if env_max_age := os.getenv("SCOUT_MAX_AGE_DAYS"):
        cfg.max_age_days = int(env_max_age)

    if env_batch := os.getenv("SCOUT_SOURCE_BATCH_LIMIT"):
        cfg.source_batch_limit = int(env_batch)

    # Catalog filtering env vars
    if env_min := os.getenv("SCOUT_MIN_EMPLOYEES"):
        cfg.min_employees = int(env_min)

    if env_max := os.getenv("SCOUT_MAX_EMPLOYEES"):
        cfg.max_employees = int(env_max)

    if env_founded := os.getenv("SCOUT_FOUNDED_AFTER"):
        cfg.founded_after = int(env_founded)

    if env_states := os.getenv("SCOUT_FILTER_STATES"):
        cfg.filter_states = [s.strip().upper() for s in env_states.split(",") if s.strip()]

    if env_industries := os.getenv("SCOUT_FILTER_INDUSTRIES"):
        cfg.filter_industries = [i.strip() for i in env_industries.split(",") if i.strip()]

    log.info(
        "Config: %d roles, max_age=%dd, batch_limit=%s, filters: employees=%s-%s, states=%s, industries=%s",
        len(cfg.roles),
        cfg.max_age_days,
        cfg.source_batch_limit or "unlimited",
        cfg.min_employees or "any",
        cfg.max_employees or "any",
        cfg.filter_states or "all",
        cfg.filter_industries or "all",
    )
    return cfg

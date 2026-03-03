"""Connection pool singleton for PostgreSQL via psycopg3."""

import logging
import os

from psycopg_pool import ConnectionPool

log = logging.getLogger("common.db")

_pool: ConnectionPool | None = None


def _fix_dsn(dsn: str) -> str:
    """Convert postgres:// to postgresql:// for psycopg3 compatibility."""
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql://", 1)
    return dsn


def get_pool() -> ConnectionPool:
    """Return a lazily-initialized connection pool singleton."""
    global _pool
    if _pool is None:
        dsn = os.environ["DATABASE_URL"]
        dsn = _fix_dsn(dsn)
        log.info("Initializing connection pool")
        _pool = ConnectionPool(conninfo=dsn, min_size=2, max_size=5, open=True)
    return _pool

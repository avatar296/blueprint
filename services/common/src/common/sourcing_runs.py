"""Sourcing run tracking — create, complete, fail runs and log provider results."""

import logging
from uuid import UUID

from common.db import get_pool

log = logging.getLogger("common.sourcing_runs")


def create_run() -> UUID:
    """Insert a new sourcing run with status='running'. Returns the run ID."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "INSERT INTO sourcing_runs (status) VALUES ('running') RETURNING id"
        ).fetchone()
    return row[0]


def complete_run(
    run_id: UUID,
    companies_before: int,
    companies_after: int,
    total_upserted: int,
) -> None:
    """Mark a sourcing run as completed with summary stats."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            UPDATE sourcing_runs
            SET status = 'completed',
                completed_at = now(),
                companies_before = %s,
                companies_after = %s,
                total_upserted = %s
            WHERE id = %s
            """,
            (companies_before, companies_after, total_upserted, run_id),
        )


def fail_run(run_id: UUID, error_message: str) -> None:
    """Mark a sourcing run as failed with an error message."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            UPDATE sourcing_runs
            SET status = 'failed',
                completed_at = now(),
                error_message = %s
            WHERE id = %s
            """,
            (error_message, run_id),
        )


def insert_provider_result(
    run_id: UUID,
    provider_name: str,
    records_fetched: int,
    records_upserted: int,
    duration_secs: float,
    error_message: str | None = None,
) -> None:
    """Record the result of a single provider within a sourcing run."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO sourcing_run_providers
                (run_id, provider_name, records_fetched, records_upserted,
                 duration_secs, error_message)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (run_id, provider_name, records_fetched, records_upserted,
             duration_secs, error_message),
        )

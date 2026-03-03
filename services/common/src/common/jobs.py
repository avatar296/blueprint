"""Job table helpers — insert, query, and status transitions."""

import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from psycopg.rows import dict_row

from common.db import get_pool
from common.models import JobInsert, JobRow, JobStatus

log = logging.getLogger("common.jobs")


def insert_job(job: JobInsert) -> UUID | None:
    """Insert a job, deduplicating on (source, source_id).

    Returns the new job's UUID if inserted, or None if it already exists.
    """
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO jobs (source, source_id, url, title, company,
                              description, location, remote,
                              salary_min, salary_max, date_posted)
            VALUES (%(source)s, %(source_id)s, %(url)s, %(title)s, %(company)s,
                    %(description)s, %(location)s, %(remote)s,
                    %(salary_min)s, %(salary_max)s, %(date_posted)s)
            ON CONFLICT (source, source_id) DO NOTHING
            RETURNING id
            """,
            job,
        ).fetchone()
    if row:
        return row[0]
    return None


def fetch_jobs_by_status(
    status: JobStatus, limit: int = 50, staleness_days: int | None = None
) -> list[JobRow]:
    """Fetch jobs with the given status, oldest first.

    Args:
        status: Only return jobs with this status.
        limit: Maximum number of rows to return.
        staleness_days: If set, exclude jobs with date_scraped older than this many days.
    """
    pool = get_pool()
    query = "SELECT * FROM jobs WHERE status = %s"
    params: list = [status.value]

    if staleness_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=staleness_days)
        query += " AND date_scraped > %s"
        params.append(cutoff)

    query += " ORDER BY date_scraped LIMIT %s"
    params.append(limit)

    with pool.connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(query, params).fetchall()
    return rows  # type: ignore[return-value]


def transition_status(
    job_id: UUID, from_status: JobStatus, to_status: JobStatus
) -> bool:
    """Atomically transition a job's status using optimistic locking.

    Returns True if the transition succeeded (row matched from_status),
    False if the row was already claimed by another process.
    """
    pool = get_pool()
    with pool.connection() as conn:
        cur = conn.execute(
            "UPDATE jobs SET status = %s WHERE id = %s AND status = %s",
            (to_status.value, job_id, from_status.value),
        )
    return cur.rowcount == 1

"""Company signals helpers — query, insert, and mark verified."""

import logging
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common.db import get_pool

log = logging.getLogger("common.signals")


def get_companies_to_verify(
    limit: int = 500,
    reverify_days: int = 30,
    min_employees: int | None = None,
    stale_ratio: float = 0.2,
) -> list[dict]:
    """Return a mix of never-verified and stale companies.

    By default 80% of the batch is fresh (verified_at IS NULL) and 20% is
    stale (verified_at older than *reverify_days*).  If either pool is too
    small the other fills the remaining slots.

    Returns list of dicts with id, name, city, state, website, source, ticker.
    """
    pool = get_pool()
    stale_limit = max(1, int(limit * stale_ratio))
    fresh_limit = limit - stale_limit

    emp_filter = ""
    emp_params: list = []
    if min_employees is not None:
        emp_filter = " AND employee_count >= %s"
        emp_params = [min_employees]

    # Two sub-selects UNIONed so each pool gets its own LIMIT,
    # then an outer LIMIT caps the total in case both are full.
    query = f"""
        (
            SELECT id, name, normalized_name, city, state, website, source, ticker
            FROM companies
            WHERE verified_at IS NULL{emp_filter}
            ORDER BY employee_count DESC NULLS LAST
            LIMIT %s
        )
        UNION ALL
        (
            SELECT id, name, normalized_name, city, state, website, source, ticker
            FROM companies
            WHERE verified_at < now() - make_interval(days => %s){emp_filter}
            ORDER BY verified_at, employee_count DESC NULLS LAST
            LIMIT %s
        )
        LIMIT %s
    """
    params: list = [*emp_params, fresh_limit, reverify_days, *emp_params, stale_limit, limit]

    with pool.connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(query, params).fetchall()
    return rows  # type: ignore[return-value]


def insert_signal(company_id: UUID, check_type: str, result: dict) -> None:
    """Insert a single signal row."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO company_signals (company_id, check_type, result)
            VALUES (%s, %s, %s)
            """,
            (company_id, check_type, Jsonb(result)),
        )


def insert_signals_batch(
    rows: list[tuple[UUID, str, dict]], *, chunk_size: int = 1_000
) -> int:
    """Batch-insert signals. Each element is (company_id, check_type, result_dict).

    Returns number of rows inserted.
    """
    if not rows:
        return 0

    pool = get_pool()
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        with pool.connection() as conn:
            with conn.cursor() as cur:
                for company_id, check_type, result in chunk:
                    cur.execute(
                        """
                        INSERT INTO company_signals (company_id, check_type, result)
                        VALUES (%s, %s, %s)
                        """,
                        (company_id, check_type, Jsonb(result)),
                    )
                    total += 1
    return total


def mark_verified(company_id: UUID) -> None:
    """Set verified_at = now() for a company."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            "UPDATE companies SET verified_at = now() WHERE id = %s",
            (company_id,),
        )


def mark_verified_batch(
    company_ids: list[UUID], *, chunk_size: int = 5_000
) -> None:
    """Batch-set verified_at = now() for a list of companies."""
    if not company_ids:
        return

    pool = get_pool()
    for start in range(0, len(company_ids), chunk_size):
        chunk = company_ids[start : start + chunk_size]
        placeholders = ", ".join(["%s"] * len(chunk))
        with pool.connection() as conn:
            conn.execute(
                f"UPDATE companies SET verified_at = now() WHERE id IN ({placeholders})",
                chunk,
            )

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

    "Verified" is derived from company_signals: a company is verified if it
    has at least one signal row.  Staleness is based on the most recent
    signal's updated_at vs *reverify_days*.

    By default 80% of the batch is fresh (no signals) and 20% is stale.
    If either pool is too small the other fills the remaining slots.

    Returns list of dicts with id, name, city, state, website, source, ticker.
    """
    pool = get_pool()
    stale_limit = max(1, int(limit * stale_ratio))
    fresh_limit = limit - stale_limit

    emp_filter = ""
    emp_params: list = []
    if min_employees is not None:
        emp_filter = " AND c.employee_count >= %s"
        emp_params = [min_employees]

    query = f"""
        (
            SELECT c.id, c.name, c.normalized_name, c.city, c.state,
                   c.website, c.source, c.ticker
            FROM companies c
            WHERE NOT EXISTS (
                SELECT 1 FROM company_signals cs WHERE cs.company_id = c.id
            ){emp_filter}
            ORDER BY c.employee_count DESC NULLS LAST
            LIMIT %s
        )
        UNION ALL
        (
            SELECT c.id, c.name, c.normalized_name, c.city, c.state,
                   c.website, c.source, c.ticker
            FROM companies c
            JOIN (
                SELECT company_id, max(updated_at) AS last_checked
                FROM company_signals
                GROUP BY company_id
                HAVING max(updated_at) < now() - make_interval(days => %s)
            ) s ON s.company_id = c.id
            {emp_filter}
            ORDER BY s.last_checked, c.employee_count DESC NULLS LAST
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
    """Upsert a single signal row (one row per company+check_type)."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO company_signals (company_id, check_type, result)
            VALUES (%s, %s, %s)
            ON CONFLICT (company_id, check_type) DO UPDATE
                SET result = EXCLUDED.result,
                    updated_at = now()
            """,
            (company_id, check_type, Jsonb(result)),
        )


def insert_signals_batch(
    rows: list[tuple[UUID, str, dict]], *, chunk_size: int = 1_000
) -> int:
    """Batch-upsert signals. Each element is (company_id, check_type, result_dict).

    Returns number of rows upserted.
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
                        ON CONFLICT (company_id, check_type) DO UPDATE
                            SET result = EXCLUDED.result,
                                updated_at = now()
                        """,
                        (company_id, check_type, Jsonb(result)),
                    )
                    total += 1
    return total



"""ATS discovery table helpers — insert, query, and fetch discovered boards."""

import logging
from uuid import UUID

from psycopg.rows import dict_row

from common.db import get_pool

log = logging.getLogger("common.discovery")


def insert_discovery(
    company_name: str,
    normalized_name: str,
    ats: str | None,
    board_id: str | None,
    company_id: UUID | None = None,
) -> None:
    """Upsert a discovery result into ats_discoveries.

    ats=None records a negative cache entry (company probed, nothing found).
    company_id links back to the companies table when probed from sourcing path.
    """
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            """
            INSERT INTO ats_discoveries (company_name, normalized_name, ats, board_id, company_id)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (normalized_name, COALESCE(ats, '__none__'))
            DO UPDATE SET
                probed_at = now(),
                active = TRUE,
                company_id = COALESCE(EXCLUDED.company_id, ats_discoveries.company_id)
            """,
            (company_name, normalized_name, ats, board_id, company_id),
        )


def fetch_active_discoveries() -> list[dict]:
    """Return all active discovered boards (ats IS NOT NULL)."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(
            """
            SELECT company_name, normalized_name, ats, board_id
            FROM ats_discoveries
            WHERE active = TRUE AND ats IS NOT NULL
            ORDER BY probed_at DESC
            """,
        ).fetchall()
    return rows  # type: ignore[return-value]


def fetch_filtered_discoveries(
    *,
    min_employees: int | None = None,
    max_employees: int | None = None,
    founded_after: int | None = None,
    states: list[str] | None = None,
    industries: list[str] | None = None,
) -> list[dict]:
    """Return active discoveries, optionally filtered by company metadata.

    Discoveries without a company_id (from search-phase path) are always included.
    Discoveries with a company_id are filtered by the provided criteria via JOIN.
    """
    pool = get_pool()

    # Build filter conditions for the companies JOIN
    company_filters: list[str] = []
    params: list = []

    if min_employees is not None:
        company_filters.append("c.employee_count >= %s")
        params.append(min_employees)

    if max_employees is not None:
        company_filters.append("c.employee_count <= %s")
        params.append(max_employees)

    if founded_after is not None:
        company_filters.append("c.date_founded >= make_date(%s, 1, 1)")
        params.append(founded_after)

    if states:
        company_filters.append("c.state = ANY(%s)")
        params.append(states)

    if industries:
        company_filters.append("c.industry = ANY(%s)")
        params.append(industries)

    # If no filters, just return all active discoveries
    if not company_filters:
        return fetch_active_discoveries()

    where_clause = " AND ".join(company_filters)

    query = f"""
        SELECT d.company_name, d.normalized_name, d.ats, d.board_id
        FROM ats_discoveries d
        WHERE d.active = TRUE AND d.ats IS NOT NULL
          AND (
              d.company_id IS NULL
              OR d.company_id IN (
                  SELECT c.id FROM companies c WHERE {where_clause}
              )
          )
        ORDER BY d.probed_at DESC
    """

    with pool.connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(query, params).fetchall()
    return rows  # type: ignore[return-value]

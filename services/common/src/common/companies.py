"""Company table helpers — upsert, query, and mark probed."""

import logging
from uuid import UUID

from psycopg.rows import dict_row

from common.db import get_pool

log = logging.getLogger("common.companies")


def upsert_company(
    name: str,
    normalized_name: str,
    source: str,
    *,
    source_id: str | None = None,
    employee_count: int | None = None,
    date_founded: str | None = None,
    state: str | None = None,
    city: str | None = None,
    industry: str | None = None,
    sic_code: str | None = None,
    website: str | None = None,
    ticker: str | None = None,
    exchange: str | None = None,
    filer_category: str | None = None,
    total_assets: int | None = None,
    naics_code: str | None = None,
    description: str | None = None,
) -> UUID:
    """Insert or update a company, preserving existing data via COALESCE.

    Returns the company UUID.
    """
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            """
            INSERT INTO companies (
                name, normalized_name, source, source_id,
                employee_count, date_founded, state, city,
                industry, sic_code, website,
                ticker, exchange, filer_category, total_assets, naics_code, description
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (normalized_name) DO UPDATE SET
                name            = COALESCE(EXCLUDED.name, companies.name),
                source          = COALESCE(companies.source, EXCLUDED.source),
                source_id       = COALESCE(companies.source_id, EXCLUDED.source_id),
                employee_count  = COALESCE(EXCLUDED.employee_count, companies.employee_count),
                date_founded    = COALESCE(EXCLUDED.date_founded, companies.date_founded),
                state           = COALESCE(EXCLUDED.state, companies.state),
                city            = COALESCE(EXCLUDED.city, companies.city),
                industry        = COALESCE(EXCLUDED.industry, companies.industry),
                sic_code        = COALESCE(EXCLUDED.sic_code, companies.sic_code),
                website         = COALESCE(EXCLUDED.website, companies.website),
                ticker          = COALESCE(EXCLUDED.ticker, companies.ticker),
                exchange        = COALESCE(EXCLUDED.exchange, companies.exchange),
                filer_category  = COALESCE(EXCLUDED.filer_category, companies.filer_category),
                total_assets    = COALESCE(EXCLUDED.total_assets, companies.total_assets),
                naics_code      = COALESCE(EXCLUDED.naics_code, companies.naics_code),
                description     = COALESCE(EXCLUDED.description, companies.description)
            RETURNING id
            """,
            (
                name, normalized_name, source, source_id,
                employee_count, date_founded, state, city,
                industry, sic_code, website,
                ticker, exchange, filer_category, total_assets, naics_code, description,
            ),
        ).fetchone()
    return row[0]


def get_unprobed_companies(
    limit: int = 50,
    min_employees: int | None = None,
    max_employees: int | None = None,
) -> list[dict]:
    """Return companies with probed_at IS NULL, ordered by employee_count DESC.

    Returns list of dicts with id, name, normalized_name.
    """
    pool = get_pool()
    query = """
        SELECT id, name, normalized_name
        FROM companies
        WHERE probed_at IS NULL
    """
    params: list = []

    if min_employees is not None:
        query += " AND employee_count >= %s"
        params.append(min_employees)

    if max_employees is not None:
        query += " AND employee_count <= %s"
        params.append(max_employees)

    query += " ORDER BY employee_count DESC NULLS LAST LIMIT %s"
    params.append(limit)

    with pool.connection() as conn:
        conn.row_factory = dict_row
        rows = conn.execute(query, params).fetchall()
    return rows  # type: ignore[return-value]


def mark_probed(company_id: UUID) -> None:
    """Set probed_at = now() for a company."""
    pool = get_pool()
    with pool.connection() as conn:
        conn.execute(
            "UPDATE companies SET probed_at = now() WHERE id = %s",
            (company_id,),
        )


def get_company_count() -> int:
    """Return total number of companies in table."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute("SELECT count(*) FROM companies").fetchone()
    return row[0]

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


def upsert_companies_batch(rows: list[tuple], *, chunk_size: int = 5_000) -> int:
    """Batch-upsert company rows using executemany in chunks.

    Each element of *rows* is a 17-tuple matching the INSERT column order
    (name, normalized_name, source, source_id, employee_count, date_founded,
     state, city, industry, sic_code, website, ticker, exchange,
     filer_category, total_assets, naics_code, description).

    Returns the number of rows sent (not necessarily new — ON CONFLICT updates
    are counted too).
    """
    if not rows:
        return 0

    sql = """
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
    """
    pool = get_pool()
    total = 0
    for start in range(0, len(rows), chunk_size):
        chunk = rows[start : start + chunk_size]
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(sql, chunk)
        total += len(chunk)
    return total


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
    """Return estimated number of companies (via pg_class for speed)."""
    pool = get_pool()
    with pool.connection() as conn:
        row = conn.execute(
            "SELECT reltuples::bigint FROM pg_class WHERE relname = 'companies'"
        ).fetchone()
    return row[0] if row and row[0] >= 0 else 0

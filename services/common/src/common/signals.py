"""Company signals helpers — query, insert, and mark verified."""

import logging
from collections.abc import Callable
from uuid import UUID

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from common.db import get_pool

log = logging.getLogger("common.signals")


_SOUTHERN_CO_CITIES = [
    'pueblo', 'colorado springs', 'canon city', 'florence', 'fountain',
    'monument', 'woodland park', 'manitou springs', 'pueblo west',
    'penrose', 'trinidad', 'walsenburg', 'la junta', 'salida',
    'rocky ford', 'buena vista',
]

# Each tier: (name, WHERE clause, extra-params factory).
# Clauses reference table alias ``c`` for companies.
_FRESH_TIERS: list[tuple[str, str, Callable[[], list]]] = [
    ("large_with_website",
     "c.employee_count >= 100 AND c.website IS NOT NULL",
     lambda: []),
    ("public_companies",
     "(c.ticker IS NOT NULL OR c.source = 'sec_edgar')"
     " AND (c.employee_count IS NULL OR c.employee_count < 100)",
     lambda: []),
    ("medium_with_website",
     "c.employee_count BETWEEN 50 AND 99 AND c.website IS NOT NULL",
     lambda: []),
    ("large",
     "c.employee_count >= 100 AND c.website IS NULL",
     lambda: []),
    ("southern_co",
     "c.state = 'CO' AND lower(c.city) = ANY(%s)",
     lambda: [_SOUTHERN_CO_CITIES]),
    ("colorado",
     "c.state = 'CO' AND (c.city IS NULL OR lower(c.city) != ALL(%s))",
     lambda: [_SOUTHERN_CO_CITIES]),
    ("medium",
     "c.employee_count BETWEEN 50 AND 99 AND c.website IS NULL",
     lambda: []),
    ("has_website",
     "c.website IS NOT NULL"
     " AND (c.employee_count IS NULL OR c.employee_count < 50)",
     lambda: []),
]

_COLS = "c.id, c.name, c.normalized_name, c.city, c.state, c.website, c.source, c.ticker"

# Skip companies whose name contains state-filing status markers (dead/defunct)
# or shell-entity patterns (holdings, trusts, etc.) with no employees or website.
_DEAD_FILTER = (
    "AND c.name NOT ILIKE '%%delinquent%%' AND c.name NOT ILIKE '%%dissolved%%'"
    " AND NOT ("
    "  c.employee_count IS NULL AND c.website IS NULL"
    "  AND (c.name ILIKE '%%holdings%%' OR c.name ILIKE '%%properties%%'"
    "       OR c.name ILIKE '%%trust%%' OR c.name ILIKE '%%investments%%'"
    "       OR c.name ILIKE '%%enterprises%%')"
    ")"
)


def _fetch_fresh_tiered(conn, remaining: int) -> list[dict]:
    """Fill *remaining* slots from highest-priority tier first."""
    rows: list[dict] = []
    for tier_name, where, params_fn in _FRESH_TIERS:
        if remaining <= 0:
            break
        query = f"""
            SELECT {_COLS}
            FROM companies c
            WHERE NOT EXISTS (
                SELECT 1 FROM company_signals cs WHERE cs.company_id = c.id
            ) AND {where}
            {_DEAD_FILTER}
            ORDER BY c.employee_count DESC NULLS LAST
            LIMIT %s
        """
        params = [*params_fn(), remaining]
        batch = conn.execute(query, params).fetchall()
        if batch:
            log.info("tier %-22s  → %d companies", tier_name, len(batch))
            rows.extend(batch)
            remaining -= len(batch)
    return rows


def _fetch_stale_tiered(conn, remaining: int, reverify_days: int) -> list[dict]:
    """Re-verify stale companies in tier order."""
    rows: list[dict] = []
    for tier_name, where, params_fn in _FRESH_TIERS:
        if remaining <= 0:
            break
        query = f"""
            SELECT {_COLS}
            FROM companies c
            JOIN (
                SELECT company_id, max(updated_at) AS last_checked
                FROM company_signals
                GROUP BY company_id
                HAVING max(updated_at) < now() - make_interval(days => %s)
            ) s ON s.company_id = c.id
            WHERE {where}
            {_DEAD_FILTER}
            ORDER BY s.last_checked, c.employee_count DESC NULLS LAST
            LIMIT %s
        """
        params = [reverify_days, *params_fn(), remaining]
        batch = conn.execute(query, params).fetchall()
        if batch:
            log.info("stale %-20s  → %d companies", tier_name, len(batch))
            rows.extend(batch)
            remaining -= len(batch)
    return rows


def get_companies_to_verify(
    limit: int = 500,
    reverify_days: int = 30,
    stale_ratio: float = 0.2,
) -> list[dict]:
    """Return a mix of never-verified and stale companies, prioritised by tier.

    Tiers (highest first — remote-friendly companies prioritised):
      1. Large companies with website (100+ employees)
      2. Public/SEC companies (ticker or sec_edgar source)
      3. Large companies without website (100+)
      4. Medium companies with website (50-99 employees)
      5. Southern Colorado (Pueblo/CO Springs corridor)
      6. Rest of Colorado
      7. Medium companies without website (50-99)
      8. Any company with a website (<50 employees)

    By default 80% of the batch is fresh (never verified) and 20% stale
    (oldest signals first).  If either pool is too small the other fills
    the remaining slots.

    Returns list of dicts with id, name, city, state, website, source, ticker.
    """
    pool = get_pool()
    stale_limit = max(1, int(limit * stale_ratio))
    fresh_limit = limit - stale_limit

    with pool.connection() as conn:
        conn.row_factory = dict_row
        fresh = _fetch_fresh_tiered(conn, fresh_limit)
        stale = _fetch_stale_tiered(conn, stale_limit, reverify_days)

    # Back-fill: if one pool is short, let the other expand.
    total = fresh + stale
    if len(total) < limit:
        shortfall = limit - len(total)
        with pool.connection() as conn:
            conn.row_factory = dict_row
            if len(fresh) < fresh_limit:
                extra = _fetch_stale_tiered(conn, shortfall, reverify_days)
                total.extend(extra)
            elif len(stale) < stale_limit:
                extra = _fetch_fresh_tiered(conn, shortfall)
                total.extend(extra)

    n_stale = len(stale)
    log.info("Batch ready: %d fresh + %d stale = %d total",
             len(total) - n_stale, n_stale, len(total))
    return total


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



-- 009: Company signals — liveness & internet presence checks
-- One row per (company_id, check_type); upserted on re-verification.
-- Verification status is derived from signal rows (no column on companies).

CREATE TABLE IF NOT EXISTS company_signals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    check_type   TEXT NOT NULL,     -- website, web_search, facebook, yelp, maps, sec
    result       JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (company_id, check_type)
);

-- Supports the stale-company query (JOIN on company_id, filter on updated_at).
CREATE INDEX IF NOT EXISTS idx_signals_company_updated
    ON company_signals (company_id, updated_at);

-- 009: Company signals — liveness & internet presence checks
-- Append-only log: one row per check per company per run.

-- Add verified_at to companies (parallel to existing probed_at)
ALTER TABLE companies ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
-- Composite index covers both verifier sub-queries (fresh + stale) with no extra sort.
CREATE INDEX IF NOT EXISTS idx_companies_verified
    ON companies (verified_at NULLS FIRST, employee_count DESC NULLS LAST);

CREATE TABLE company_signals (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_id   UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    check_type   TEXT NOT NULL,     -- website, web_search, facebook, yelp, maps, sec
    result       JSONB NOT NULL DEFAULT '{}',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Latest signal per company+check_type
CREATE INDEX idx_company_signals_latest
    ON company_signals (company_id, check_type, created_at DESC);

-- Blueprint database schema
-- Runs automatically on first PostgreSQL start via docker-entrypoint-initdb.d

-- Job pipeline status enum
CREATE TYPE job_status AS ENUM (
    'scraped',
    'scoring',
    'scored',
    'reviewing',
    'approved',
    'rejected',
    'generating',
    'applying',
    'applied',
    'error'
);

-- Core jobs table
CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Source metadata
    source          TEXT NOT NULL,           -- 'linkedin', 'indeed', etc.
    source_id       TEXT NOT NULL,           -- platform-specific job ID
    url             TEXT,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    description     TEXT,
    location        TEXT,
    remote          BOOLEAN DEFAULT FALSE,
    salary_min      INTEGER,
    salary_max      INTEGER,
    date_posted     TIMESTAMPTZ,
    date_scraped    TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Scoring
    fit_score       SMALLINT CHECK (fit_score >= 0 AND fit_score <= 100),
    score_rationale TEXT,
    scored_at       TIMESTAMPTZ,

    -- Pipeline status
    status          job_status NOT NULL DEFAULT 'scraped',

    -- Application tracking
    applied_at      TIMESTAMPTZ,
    resume_path     TEXT,

    -- Audit
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes
CREATE INDEX idx_jobs_status ON jobs (status);
CREATE INDEX idx_jobs_fit_score ON jobs (fit_score DESC NULLS LAST);
CREATE INDEX idx_jobs_source_source_id ON jobs (source, source_id);
CREATE INDEX idx_jobs_date_scraped ON jobs (date_scraped DESC);

-- Deduplication: one entry per source+source_id
CREATE UNIQUE INDEX idx_jobs_dedup ON jobs (source, source_id);

-- Auto-update updated_at on row modification
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

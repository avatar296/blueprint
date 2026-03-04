-- Sourcing run tracking: record each pipeline execution and per-provider results
-- for monitoring, debugging, and auditing sourcing activity.

CREATE TABLE sourcing_runs (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    started_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at      TIMESTAMPTZ,
    status            TEXT NOT NULL DEFAULT 'running'
                      CHECK (status IN ('running', 'completed', 'failed')),
    companies_before  BIGINT,
    companies_after   BIGINT,
    total_upserted    BIGINT,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sourcing_runs_status ON sourcing_runs (status);
CREATE INDEX idx_sourcing_runs_started ON sourcing_runs (started_at DESC);

CREATE TRIGGER trg_sourcing_runs_updated_at
    BEFORE UPDATE ON sourcing_runs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

CREATE TABLE sourcing_run_providers (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id           UUID NOT NULL REFERENCES sourcing_runs(id) ON DELETE CASCADE,
    provider_name    TEXT NOT NULL,
    records_fetched  BIGINT NOT NULL DEFAULT 0,
    records_upserted BIGINT NOT NULL DEFAULT 0,
    duration_secs    DOUBLE PRECISION,
    error_message    TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sourcing_run_providers_run ON sourcing_run_providers (run_id);

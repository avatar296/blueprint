-- Company sourcing: store enriched company metadata from public data sources
-- (SEC EDGAR, Wikidata) for ATS probing and catalog filtering.

CREATE TABLE companies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    employee_count  INTEGER,
    date_founded    DATE,
    state           TEXT,               -- US state code ('CO', 'CA')
    city            TEXT,               -- city name
    industry        TEXT,               -- human-readable industry name
    sic_code        TEXT,               -- SEC Standard Industrial Classification code
    website         TEXT,
    source          TEXT,                -- 'sec_edgar', 'wikidata'
    source_id       TEXT,               -- CIK, Wikidata QID, etc.
    probed_at       TIMESTAMPTZ,        -- when ATS discovery last probed this company
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX idx_companies_dedup ON companies (normalized_name);
CREATE INDEX idx_companies_probed ON companies (probed_at NULLS FIRST);
CREATE INDEX idx_companies_employee_count ON companies (employee_count) WHERE employee_count IS NOT NULL;
CREATE INDEX idx_companies_state ON companies (state) WHERE state IS NOT NULL;

CREATE TRIGGER trg_companies_updated_at
    BEFORE UPDATE ON companies
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at();

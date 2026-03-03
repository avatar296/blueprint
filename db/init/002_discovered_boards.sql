-- ATS auto-discovery: cache probed career boards (Greenhouse, Lever)
-- Runs automatically on fresh DB via docker-entrypoint-initdb.d

CREATE TABLE ats_discoveries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name    TEXT NOT NULL,       -- raw name from jobs table
    normalized_name TEXT NOT NULL,       -- lowercased, suffix-stripped dedup key
    ats             TEXT,                -- 'greenhouse'/'lever', NULL = nothing found
    board_id        TEXT,                -- slug that returned 200, NULL if nothing found
    probed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    active          BOOLEAN NOT NULL DEFAULT TRUE
);

-- One row per normalized name + ATS (NULL ATS = negative cache)
CREATE UNIQUE INDEX idx_ats_disc_dedup
    ON ats_discoveries (normalized_name, COALESCE(ats, '__none__'));
CREATE INDEX idx_ats_disc_normalized ON ats_discoveries (normalized_name);
CREATE INDEX idx_ats_disc_active ON ats_discoveries (active) WHERE active = TRUE AND ats IS NOT NULL;

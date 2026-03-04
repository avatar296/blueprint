-- 010: Migrate company_signals from append-only to upsert model.
-- Adds updated_at, deduplicates existing rows, adds unique constraint.

-- 1. Add updated_at column (defaults to created_at for existing rows)
ALTER TABLE company_signals
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
UPDATE company_signals SET updated_at = created_at WHERE updated_at IS NULL;
ALTER TABLE company_signals
    ALTER COLUMN updated_at SET NOT NULL,
    ALTER COLUMN updated_at SET DEFAULT now();

-- 2. Deduplicate: keep only the newest row per (company_id, check_type)
DELETE FROM company_signals a
USING company_signals b
WHERE a.company_id = b.company_id
  AND a.check_type = b.check_type
  AND a.created_at < b.created_at;

-- Handle exact timestamp ties (keep lowest id)
DELETE FROM company_signals a
USING company_signals b
WHERE a.company_id = b.company_id
  AND a.check_type = b.check_type
  AND a.created_at = b.created_at
  AND a.id > b.id;

-- 3. Add unique constraint
ALTER TABLE company_signals
    ADD CONSTRAINT company_signals_company_check_uq
    UNIQUE (company_id, check_type);

-- 4. Drop the old index (unique constraint replaces it)
DROP INDEX IF EXISTS idx_company_signals_latest;

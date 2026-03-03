-- Merge duplicate companies that share the same normalized_name across sources.
-- Keep the row with the most data; absorb missing fields from others.

-- Step 1: For each normalized_name with multiple rows, merge data into the oldest row
WITH ranked AS (
    SELECT id, normalized_name,
           ROW_NUMBER() OVER (PARTITION BY normalized_name ORDER BY created_at) AS rn
    FROM companies
),
dupes AS (
    SELECT r.id AS keep_id, c2.id AS drop_id, r.normalized_name
    FROM ranked r
    JOIN companies c2 ON c2.normalized_name = r.normalized_name AND c2.id != r.id
    WHERE r.rn = 1
)
UPDATE companies c SET
    employee_count = COALESCE(c.employee_count, src.employee_count),
    date_founded   = COALESCE(c.date_founded, src.date_founded),
    state          = COALESCE(c.state, src.state),
    city           = COALESCE(c.city, src.city),
    industry       = COALESCE(c.industry, src.industry),
    sic_code       = COALESCE(c.sic_code, src.sic_code),
    website        = COALESCE(c.website, src.website),
    source_id      = COALESCE(c.source_id, src.source_id)
FROM dupes d
JOIN companies src ON src.id = d.drop_id
WHERE c.id = d.keep_id;

-- Step 2: Delete the duplicate rows
WITH ranked AS (
    SELECT id, normalized_name,
           ROW_NUMBER() OVER (PARTITION BY normalized_name ORDER BY created_at) AS rn
    FROM companies
)
DELETE FROM companies WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

-- Step 3: Replace the unique index
DROP INDEX idx_companies_dedup;
CREATE UNIQUE INDEX idx_companies_dedup ON companies (normalized_name);

-- Step 4: Make source nullable (multiple sources now merge into one row)
ALTER TABLE companies ALTER COLUMN source DROP NOT NULL;

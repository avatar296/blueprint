# Blueprint — development task runner
# Usage: just <recipe>    (run `just --list` for all recipes)

set dotenv-load
set shell := ["bash", "-euo", "pipefail", "-c"]

db_user := env("POSTGRES_USER", "blueprint")
db_name := env("POSTGRES_DB", "blueprint")
db_pass := env("POSTGRES_PASSWORD", "changeme")
db_port := env("POSTGRES_PORT", "5432")
db_url  := "postgresql://" + db_user + ":" + db_pass + "@localhost:" + db_port + "/" + db_name

# ---------- database ----------

# Start postgres and wait for healthy
db-up:
    docker compose up -d postgres
    @echo "Waiting for postgres..."
    @until docker compose exec postgres pg_isready -q 2>/dev/null; do sleep 1; done
    @echo "Postgres is ready."

# Tear down everything (containers + volumes) and start fresh
db-reset:
    docker compose down -v
    just db-up

# Run a SQL query: just db-query "SELECT count(*) FROM companies"
db-query sql:
    docker compose exec postgres psql -U {{db_user}} -d {{db_name}} -c "{{sql}}"

# Open an interactive psql shell
db-shell:
    docker compose exec postgres psql -U {{db_user}} -d {{db_name}}

# Create a compressed pg_dump snapshot in backups/
db-backup:
    mkdir -p backups
    docker compose exec postgres pg_dump -Fc -U {{db_user}} {{db_name}} > backups/blueprint_$(date +%Y-%m-%d_%H%M%S).dump
    @echo "Backup saved to backups/"
    @ls -lh backups/*.dump | tail -1

# Restore from a backup file: just db-restore blueprint_2025-01-01_120000.dump
db-restore file:
    docker compose exec -T postgres pg_restore --clean --if-exists -U {{db_user}} -d {{db_name}} < backups/{{file}}
    @echo "Restored from backups/{{file}}"

# List available backups with sizes
db-backup-list:
    @ls -lh backups/

# ---------- sourcing ----------

# Run company sourcing pipeline (SEC EDGAR, Wikidata, ProPublica, CO/TX/NY/OR/IA SOS, FDIC, NCUA, SBA PPP, OSHA)
# Usage: just sourcing [BATCH_LIMIT]  (default: 0 = unlimited)
sourcing batch="0":
    DATABASE_URL="{{db_url}}" uv run python -c "\
    import logging; \
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'); \
    from scout.sourcing_runner import run_sourcing; \
    run_sourcing(source_batch_limit={{batch}})"

# Quick check: data completeness after sourcing
sourcing-stats:
    just db-query "SELECT count(*) AS total, \
        count(ticker) AS has_ticker, \
        count(exchange) AS has_exchange, \
        count(filer_category) AS has_filer_cat, \
        count(total_assets) AS has_assets, \
        count(description) AS has_description, \
        count(city) AS has_city, \
        count(state) AS has_state, \
        count(employee_count) AS has_employees \
    FROM companies"

# Per-provider breakdown
sourcing-by-source:
    just db-query "SELECT source, count(*) AS total, \
        count(employee_count) AS has_employees, \
        count(city) AS has_city, \
        count(state) AS has_state, \
        count(naics_code) AS has_naics \
    FROM companies GROUP BY source ORDER BY total DESC"

# ---------- verification ----------

# Run company verification (website liveness, DDG search, SEC filings)
# Usage: just verify [BATCH_SIZE]  (default: 500)
verify batch="500":
    DATABASE_URL="{{db_url}}" VERIFIER_BATCH_SIZE={{batch}} OLLAMA_BASE_URL="http://localhost:11434" uv run python -c "\
    import logging; \
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'); \
    logging.getLogger('ddgs').setLevel(logging.WARNING); \
    logging.getLogger('httpx').setLevel(logging.WARNING); \
    logging.getLogger('primp').setLevel(logging.WARNING); \
    from verifier.config import load_config; \
    from verifier.runner import run_verification; \
    cfg = load_config(); \
    cfg.batch_size = {{batch}}; \
    run_verification( \
        batch_size=cfg.batch_size, reverify_days=cfg.reverify_days, \
        website_concurrency=cfg.website_concurrency, ddg_limit=cfg.ddg_daily_limit, \
        sec_concurrency=cfg.sec_concurrency, discovery_concurrency=cfg.discovery_concurrency, \
        ollama_base_url=cfg.ollama_base_url, ollama_model=cfg.ollama_model, \
        ollama_timeout=cfg.ollama_timeout, ollama_vision_model=cfg.ollama_vision_model, \
        ollama_vision_timeout=cfg.ollama_vision_timeout, \
        use_langgraph=cfg.use_langgraph, \
    )"

# Run verifier in continuous loop (processes batches until Ctrl-C)
# Usage: just verify-loop [BATCH_SIZE]  (default: 500)
verify-loop batch="500":
    DATABASE_URL="{{db_url}}" VERIFIER_BATCH_SIZE={{batch}} OLLAMA_BASE_URL="http://localhost:11434" uv run python -m verifier.main

# Verification stats
verify-stats:
    just db-query "SELECT check_type, count(*) AS total, \
        count(*) FILTER (WHERE result->>'website_reachable' = 'true') AS reachable, \
        count(*) FILTER (WHERE result->>'yelp_closed' = 'true') AS closed \
    FROM company_signals GROUP BY check_type ORDER BY check_type"

# ---------- leads ----------

# Export leads CSV — companies operating without a real website but with positive signals
export-leads:
    mkdir -p data
    docker compose exec postgres psql -U {{db_user}} -d {{db_name}} \
      -c "\COPY ( \
        SELECT \
          c.name                                          AS company_name, \
          c.city, \
          c.state, \
          c.employee_count, \
          ws.result->>'search_top_url'                    AS website_found, \
          fb.result->>'facebook_url'                      AS facebook_url, \
          yl.result->>'yelp_url'                          AS yelp_url, \
          NOT (yl.result->>'yelp_closed')::boolean        AS yelp_open, \
          mp.result->>'gmaps_name'                        AS gmaps_name, \
          cr.result->>'careers_url'                        AS careers_url, \
          ct.result->>'contact_email'                      AS email, \
          ct.result->>'contact_phone'                      AS phone, \
          CASE \
            WHEN c.employee_count >= 100 THEN 'large' \
            WHEN c.employee_count >= 50  THEN 'medium' \
            WHEN c.employee_count >= 10  THEN 'small' \
            ELSE 'micro' \
          END                                              AS lead_tier \
        FROM companies c \
        LEFT JOIN company_signals ws ON ws.company_id = c.id AND ws.check_type = 'web_search' \
        LEFT JOIN company_signals fb ON fb.company_id = c.id AND fb.check_type = 'facebook' \
        LEFT JOIN company_signals yl ON yl.company_id = c.id AND yl.check_type = 'yelp' \
        LEFT JOIN company_signals mp ON mp.company_id = c.id AND mp.check_type = 'maps' \
        LEFT JOIN company_signals cr ON cr.company_id = c.id AND cr.check_type = 'careers' \
        LEFT JOIN company_signals ct ON ct.company_id = c.id AND ct.check_type = 'contact' \
        WHERE c.name NOT ILIKE '%%delinquent%%' \
          AND c.name NOT ILIKE '%%dissolved%%' \
          AND EXISTS ( \
            SELECT 1 FROM company_signals cs WHERE cs.company_id = c.id \
          ) \
          AND ( \
            ws.result->>'search_top_url' IS NULL \
            OR ws.result->>'search_top_url' ~ '(yelp\.com|facebook\.com|yellowpages\.com|bbb\.org|manta\.com|dnb\.com|bizapedia\.com|opencorporates\.com|bloomberg\.com|sec\.gov|linkedin\.com)' \
          ) \
          AND ( \
            (yl.result->>'yelp_url' IS NOT NULL AND (yl.result->>'yelp_closed')::boolean IS DISTINCT FROM true) \
            OR fb.result->>'facebook_url' IS NOT NULL \
            OR mp.result->>'gmaps_name' IS NOT NULL \
          ) \
        ORDER BY c.employee_count DESC NULLS LAST \
      ) TO STDOUT WITH CSV HEADER" \
      > data/leads_$(date +%Y-%m-%d).csv
    @echo "Exported to data/"
    @wc -l data/leads_*.csv | tail -1

# Export careers CSV — companies with discovered career pages and ATS platforms
export-careers:
    mkdir -p data
    docker compose exec postgres psql -U {{db_user}} -d {{db_name}} \
      -c "\COPY ( \
        SELECT \
          c.name                                          AS company_name, \
          c.city, \
          c.state, \
          c.employee_count, \
          cr.result->>'careers_url'                        AS careers_url, \
          cr.result->>'ats_platform'                       AS ats_platform, \
          cr.result->>'ats_url'                            AS ats_url, \
          ct.result->>'contact_email'                      AS email, \
          ct.result->>'contact_phone'                      AS phone \
        FROM companies c \
        JOIN company_signals cr ON cr.company_id = c.id AND cr.check_type = 'careers' \
        LEFT JOIN company_signals ct ON ct.company_id = c.id AND ct.check_type = 'contact' \
        WHERE cr.result->>'careers_url' IS NOT NULL \
        ORDER BY c.employee_count DESC NULLS LAST \
      ) TO STDOUT WITH CSV HEADER" \
      > data/careers_$(date +%Y-%m-%d).csv
    @echo "Exported to data/"
    @wc -l data/careers_*.csv | tail -1

# Export remote-friendly companies CSV — filtered to industries likely to have remote tech roles
export-remote:
    mkdir -p data
    docker compose exec postgres psql -U {{db_user}} -d {{db_name}} \
      -c "\COPY ( \
        SELECT \
          c.name                                          AS company_name, \
          c.industry, \
          c.city, \
          c.state, \
          c.employee_count, \
          c.website, \
          c.ticker, \
          c.exchange, \
          c.source, \
          ws.result->>'search_top_url'                    AS website_found, \
          cr.result->>'careers_url'                        AS careers_url, \
          cr.result->>'ats_platform'                       AS ats_platform, \
          cr.result->>'ats_url'                            AS ats_url, \
          ct.result->>'contact_email'                      AS email, \
          ct.result->>'contact_phone'                      AS phone \
        FROM companies c \
        LEFT JOIN company_signals ws ON ws.company_id = c.id AND ws.check_type = 'web_search' \
        LEFT JOIN company_signals cr ON cr.company_id = c.id AND cr.check_type = 'careers' \
        LEFT JOIN company_signals ct ON ct.company_id = c.id AND ct.check_type = 'contact' \
        WHERE c.name NOT ILIKE '%%delinquent%%' \
          AND c.name NOT ILIKE '%%dissolved%%' \
          AND EXISTS ( \
            SELECT 1 FROM company_signals cs WHERE cs.company_id = c.id \
          ) \
          AND ( \
            (c.employee_count >= 100 AND c.website IS NOT NULL) \
            OR ((c.ticker IS NOT NULL OR c.source = 'sec_edgar') AND (c.employee_count IS NULL OR c.employee_count < 100)) \
            OR (c.employee_count BETWEEN 50 AND 99 AND c.website IS NOT NULL) \
          ) \
          AND c.industry IS NOT NULL \
          AND NOT c.industry ILIKE ANY(ARRAY[ \
            'Real Estate Investment Trusts', 'Real Estate', \
            'Real Estate Agents & Managers%%', 'Operative Builders', \
            'real estate investment trust', 'real estate development', \
            'Opeators of%%', 'Operators of%%', 'Land Subdividers%%', 'renting', \
            'State Commercial Banks', 'National Commercial Banks', \
            'Savings Institution%%', 'Commercial Banks%%', 'Credit Union', \
            'economics of banking', 'bank', \
            'Crude Petroleum%%', 'Oil & Gas Field%%', 'Drilling Oil%%', \
            'petroleum industry', 'petroleum', 'Metal Mining', \
            'Gold and Silver%%', 'Silver Ores', 'Mining%%', 'mining', \
            'mining industry', 'quarry', 'Mineral Royalty%%', \
            'Oil Royalty%%', 'Bituminous Coal%%', \
            'Electric Services', 'Electric & Other Services%%', \
            'Gas & Other Services%%', 'Natural Gas%%', 'Water Supply', \
            'electricity generation', 'Cogeneration%%', \
            'Retail-Eating%%', 'Hotels & Motels', 'restaurant', \
            'fast food', 'gastronomy', 'hospitality industry', \
            'fast casual restaurant', 'Hotels, Rooming%%', 'resort', \
            'system catering', 'cruise line', \
            'Retail-Auto Dealers%%', 'Retail-Grocery%%', \
            'Retail-Building Materials%%', 'Retail-Lumber%%', \
            'Retail-Drug Stores%%', 'Retail-Furniture%%', \
            'Retail-Shoe%%', 'Retail-Convenience%%', 'Retail-Food Stores', \
            'Retail-Home Furniture%%', 'Retail-Variety%%', \
            'truck stop', 'outlet store', 'toy store', \
            'Agricultural Production%%', 'Agricultural Services', \
            'agriculture', 'agribusiness', 'Agricultural Prod-Livestock%%', \
            'Heavy Construction%%', 'General Bldg Contractors%%', \
            'Construction - Special Trade%%', 'Water, Sewer, Pipeline%%', \
            'Electrical Work', 'construction', 'Construction', \
            'Trucking%%', 'Water Transportation', 'Deep Sea Foreign%%', \
            'Pipe Lines%%', 'Truck & Bus Bodies', 'Truck Trailers', \
            'Motor Homes', 'Mobile Homes', 'rail transport', \
            'Railroads%%', 'taxi service', \
            'Blank Checks', \
            'Meat Packing%%', 'Poultry Slaughtering%%', \
            'meatpacking industry', 'dairy industry', 'dairy product', \
            'Refuse Systems', 'Hazardous Waste%%', 'prison', 'sex industry' \
          ]) \
        ORDER BY c.employee_count DESC NULLS LAST \
      ) TO STDOUT WITH CSV HEADER" \
      > data/remote_companies_$(date +%Y-%m-%d).csv
    @echo "Exported to data/"
    @wc -l data/remote_companies_$(date +%Y-%m-%d).csv

# ---------- dev tools ----------

# Lint all Python services
lint:
    uv run ruff check services/

# Run all tests
test:
    uv run pytest

# Sync venv after dependency changes
sync:
    uv sync

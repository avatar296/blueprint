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
    DATABASE_URL="{{db_url}}" VERIFIER_BATCH_SIZE={{batch}} uv run python -c "\
    import logging; \
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(name)s] %(levelname)s: %(message)s'); \
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
    )"

# Verification stats
verify-stats:
    just db-query "SELECT check_type, count(*) AS total, \
        count(*) FILTER (WHERE result->>'website_reachable' = 'true') AS reachable, \
        count(*) FILTER (WHERE result->>'yelp_closed' = 'true') AS closed \
    FROM company_signals GROUP BY check_type ORDER BY check_type"

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

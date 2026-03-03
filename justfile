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

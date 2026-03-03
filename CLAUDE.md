# CLAUDE.md

## Project Overview

Blueprint is a modular, agentic AI engine that automates end-to-end job acquisition. It replaces manual job searching with an automated scouting system targeting senior-level roles (Principal Architect, Data Scientist, Staff Engineer) in the Pueblo/Colorado Springs corridor and remote.

## Architecture

> For detailed architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

Four decoupled, containerized layers:

1. **Scout (Ingestion)** — Python + Playwright (stealth mode). Scrapes LinkedIn, Indeed, and niche boards.
2. **Evaluator (Logic)** — LangChain + Llama 3/Ollama. Scores job descriptions 0-100 against the Master Profile (tech stack, experience, education).
3. **Dashboard (Human-in-the-Loop)** — Next.js with Tailwind CSS ("Mountain Modern Slate & Teal" UI). Review, edit, and approve ranked opportunities.
4. **Applier (Execution)** — Playwright + Headless LaTeX. Generates ATS-optimized PDFs and automates form entry (Workday, Lever).

## Tech Stack

- **Language/Runtime:** Python, Node.js
- **Browser Automation:** Playwright
- **AI/LLM:** LangChain, Ollama (Llama 3, local)
- **Frontend:** Next.js + Tailwind CSS
- **Database:** PostgreSQL
- **Identity/Auth:** Authentik (OIDC)
- **Infrastructure:** Hetzner dedicated server (Ubuntu 24.04)
- **Deployment:** Coolify (self-hosted CI/CD), GitHub webhook triggers

## Project Structure

```
blueprint/
├── docker-compose.yml              # All services, DB, Ollama
├── .env.example                    # Environment variable template
├── data/
│   └── master_profile.json         # Career profile (gitignored)
├── db/
│   └── init/001_schema.sql         # PostgreSQL schema (jobs table, enums)
├── docs/
│   └── adr/                        # Architecture Decision Records
└── services/
    ├── scout/                      # Python + Playwright scraper
    ├── evaluator/                  # Python + LangChain scorer
    ├── applier/                    # Python + LaTeX + Playwright
    └── dashboard/                  # Next.js + Tailwind CSS
```

## Key Data Files

- `/data/master_profile.json` — 20-year technical career profile used for JD scoring
- `docker-compose.yml` — Service orchestration (PostgreSQL, Ollama, all 4 services)
- `.env.example` — Environment variable template (copy to `.env`)
- `db/init/001_schema.sql` — PostgreSQL schema (jobs table, status enum, indexes)
- `docs/adr/` — Architecture Decision Records (10 ADRs documenting key choices)
- `ARCHITECTURE.md` — Detailed system architecture, data flow, deployment topology, and security model
- `.env` — Ollama API endpoints and service config (gitignored)

## Build & Run Commands

### Full Stack (Docker)
- `docker compose up --build` — build and start all services
- `docker compose down` — stop all services
- `docker compose down -v` — stop and remove volumes (resets DB)
- `docker compose logs -f <service>` — tail logs for a service

### Python Dev Setup (one-time)
- `curl -LsSf https://astral.sh/uv/install.sh | sh` — install uv
- `uv sync` — create .venv, install all packages (editable) + dev tools
- `uv run playwright install chromium` — install browser for applier

### Python Services (all use the root .venv)
- `uv run python -m scout.main` — run scout locally
- `uv run python -m evaluator.main` — run evaluator locally
- `uv run python -m applier.main` — run applier locally
- `uv run ruff check services/` — lint all Python services
- `uv run pytest` — run all tests
- `uv sync` — re-sync after changing any pyproject.toml

### Dashboard (Next.js)
- `cd services/dashboard && npm install` — install dependencies
- `npm run dev` — start dev server on :3000
- `npm run build` — production build
- `npm run lint` — lint

## Development Notes

- All data stays on the private Hetzner server (data sovereignty by design)
- CI/CD: push to GitHub triggers Coolify automatic build pipeline via signed webhooks
- Python dev environment uses a single root `.venv` managed by `uv` workspace. Run `uv sync` after pulling.

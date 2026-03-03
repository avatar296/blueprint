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

## Key Data Files

- `/data/master_profile.json` — 20-year technical career profile used for JD scoring
- `ARCHITECTURE.md` — Detailed system architecture, data flow, deployment topology, and security model
- `.env` — LinkedIn/Indeed credentials, Ollama API endpoints

## Development Notes

- No build/test/lint commands yet — will be added as code matures
- All data stays on the private Hetzner server (data sovereignty by design)
- CI/CD: push to GitHub triggers Coolify automatic build pipeline via signed webhooks

# Blueprint: Sovereign Career Architecture

Blueprint is a modular, agentic AI engine designed to automate the end-to-end job acquisition pipeline. Built by a Lead System Architect for senior-level career transitions, it replaces the manual "spray and pray" job search with a high-precision, data-sovereign, and automated scouting system.

## The Vision

In a market saturated with high-volume, low-quality job postings, Blueprint treats a career search as an architectural problem. By leveraging Agentic AI and Browser Automation, Blueprint scouts roles in the Pueblo/Colorado Springs corridor (and remote), evaluates them against a 20-year Master Profile, and prepares "ATS-optimized" applications—all while running on private, self-hosted hardware.

## System Architecture

Blueprint is designed with a decoupled, containerized architecture managed via Coolify on a dedicated Hetzner node.

### 1. The Scout (Ingestion Layer)

- **Engine:** Python + Playwright (Stealth Mode).
- **Function:** Automated scraping of LinkedIn, Indeed, and niche boards.
- **Filtering:** Targets specific senior roles (Principal Architect, Data Scientist, Staff Engineer).

### 2. The Evaluator (Logic Layer)

- **Engine:** LangChain + Local LLM (Llama 3/Ollama).
- **Function:** Performs a multi-point comparison between Job Descriptions (JD) and a JSON Master Profile.
- **Scoring:** Outputs a 0-100 "Fit Score" based on tech stack (AWS, MS SQL, Next.js), experience (20+ years), and education (MSCS).

### 3. The Dashboard (Human-in-the-Loop)

- **Engine:** Next.js (Mountain Modern Slate & Teal UI).
- **Function:** A centralized "Recruiter Command Center" to review, edit, and approve ranked opportunities.

### 4. The Applier (Execution Layer)

- **Engine:** Playwright + Headless LaTeX.
- **Function:** Dynamically generates a custom, ATS-optimized PDF for every application and automates form entry on platforms like Workday and Lever.

## Tech Stack

| Component | Technology | Version |
|---|---|---|
| Database | PostgreSQL | 16 (alpine) |
| Backend | Python | 3.12 (slim) |
| Frontend | Next.js + React | 15 / 19 |
| Styling | Tailwind CSS | 4 |
| Browser Automation | Playwright | ≥1.49 |
| AI/LLM | LangChain + Ollama (Llama 3) | ≥0.3 |
| PDF Generation | LaTeX (TeX Live) + Jinja2 | ≥3.1 |
| Runtime | Node.js | 20 (alpine) |
| Identity | Authentik (OIDC) | Deferred |
| Infrastructure | Hetzner Dedicated | Ubuntu 24.04 |
| Orchestration | Docker Compose (dev) / Coolify (prod) | — |

## Data Sovereignty & Security

Unlike third-party "Auto-Apply" SaaS tools, Blueprint prioritizes security:

- **Privacy:** Your 20-year career history and PII never leave your private server.
- **Identity:** All administrative access is guarded by Authentik SSO.
- **Integrity:** Uses signed Webhooks for CI/CD updates from GitHub to Coolify.

## Getting Started

1. **Clone the repo:**
   ```bash
   git clone https://github.com/your-org/blueprint.git && cd blueprint
   ```

2. **Configure environment:**
   ```bash
   cp .env.example .env
   # Edit .env — set POSTGRES_PASSWORD and any job board credentials
   ```

3. **Define Master Profile:** Populate `data/master_profile.json` with your full technical history.

4. **Start all services:**
   ```bash
   docker compose up --build
   ```

5. **Pull the LLM model:**
   ```bash
   docker compose exec ollama ollama pull llama3
   ```

6. **Open the Dashboard:** [http://localhost:3000](http://localhost:3000)

For production deployment, push to GitHub to trigger the Coolify automatic build pipeline.

## Architecture

For detailed architecture documentation, see [ARCHITECTURE.md](ARCHITECTURE.md).

---

*Built in Walsenburg, CO. Architecting the future of technical career transitions.*

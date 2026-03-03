# ADR-008: Single-Server Private Infrastructure on Hetzner

## Status

Accepted

## Context

Blueprint needs infrastructure to run four services, a database, and an LLM. Options include:

- Cloud PaaS (Heroku, Railway, Fly.io) — easy deployment but data leaves your control
- Cloud IaaS (AWS, GCP, Azure) — flexible but complex, and career data transits third-party infrastructure
- Dedicated server (Hetzner, OVH) — full physical control, fixed monthly cost, no egress fees

Data sovereignty is a hard requirement (see ADR-002). The workload is predictable: one user, low-volume batch processing, one LLM instance.

## Decision

Run all services on a single Hetzner dedicated server running Ubuntu 24.04. Use Docker Compose for local development and Coolify for production container orchestration and CI/CD.

## Consequences

- **Full data sovereignty.** The server is a dedicated physical machine, not a shared VM. No third-party cloud provider processes or stores career data.
- **Fixed cost.** Predictable monthly pricing with no surprise egress or compute charges.
- **Single point of failure.** If the server goes down, the entire pipeline stops. Acceptable for a personal job search tool where hours of downtime are tolerable.
- **No auto-scaling.** Fixed resources. Not a concern at current scale (one user, batch processing).
- **Self-managed.** OS updates, backups, and security patches are the operator's responsibility. Coolify handles container lifecycle but not the host OS.

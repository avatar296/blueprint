# ADR-009: Polling-Based Service Architecture via PostgreSQL

## Status

Accepted

## Context

Services need to know when new work is available. Options include:

- Event-driven (message broker, PostgreSQL LISTEN/NOTIFY) — immediate reaction to new work
- Polling on intervals — each service queries PostgreSQL periodically for rows in its target status
- Webhook/HTTP push — services notify each other directly

Given that PostgreSQL is already the shared data bus (ADR-001) and the workload is low-volume batch processing, the simplest coordination mechanism is preferred.

## Decision

Each service polls PostgreSQL on a configurable interval:

- **Scout:** Runs a scraping cycle every `SCOUT_INTERVAL_MINUTES` (default: 60 minutes)
- **Evaluator:** Checks for unscored jobs every `EVALUATOR_INTERVAL_MINUTES` (default: 5 minutes)
- **Applier:** Checks for approved jobs ready for application generation

Intervals are configured via environment variables in `docker-compose.yml`.

## Consequences

- **Maximum simplicity.** No event infrastructure, no LISTEN/NOTIFY channels, no webhook registration. Each service is a standalone loop.
- **Configurable cadence.** Polling intervals are tunable per-service via environment variables without code changes.
- **Latency.** A newly scored job may wait up to one polling interval before the next service picks it up. At 5-minute intervals, this is a non-issue for a job search pipeline.
- **Wasted queries.** Services poll even when no new work exists. At one query per 5 minutes against a small table, the database load is negligible.
- **Easy to upgrade.** If latency becomes a concern, PostgreSQL LISTEN/NOTIFY can be added without changing the data model.

# ADR-001: Use PostgreSQL as the Shared Data Bus Between Services

## Status

Accepted

## Context

Blueprint has four decoupled services (Scout, Evaluator, Dashboard, Applier) that need to share state. The main options are:

- A message broker (RabbitMQ, Redis Streams, Kafka) for event-driven communication
- A shared database that all services read from and write to
- Direct service-to-service HTTP/gRPC calls

The project runs on a single Hetzner dedicated server with a small, fixed number of services. Throughput requirements are low (hundreds of jobs per day, not millions). The team is one developer.

## Decision

Use PostgreSQL as the sole integration layer between services. All services connect directly to the same PostgreSQL instance. Pipeline state is tracked via a `job_status` ENUM column on the `jobs` table. Each service queries for rows in the status it cares about, processes them, and advances the status.

## Consequences

- **Simpler infrastructure.** No broker to deploy, monitor, or debug. One fewer container and one fewer failure mode.
- **Single source of truth.** The `jobs` table is both the work queue and the audit log. No split-brain between a broker and a database.
- **Familiar tooling.** Standard SQL for debugging, `psql` for ad-hoc queries, pg_dump for backups.
- **Coupling to PostgreSQL.** All services share a schema. Schema migrations must be coordinated, and a database outage stops the entire pipeline.
- **No backpressure or fan-out.** Services poll on intervals rather than reacting to events. This is acceptable at current scale but would need revisiting if throughput requirements grow significantly.

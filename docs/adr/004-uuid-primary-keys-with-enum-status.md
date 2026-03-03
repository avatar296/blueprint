# ADR-004: UUID Primary Keys with PostgreSQL ENUM Status

## Status

Accepted

## Context

The `jobs` table is the central data structure in Blueprint. Key design choices:

- **Primary key type:** Auto-incrementing integers vs UUIDs
- **Status tracking:** Free-text strings, integer codes, or a PostgreSQL ENUM type

Jobs are created by the Scout service and referenced by every other service. The pipeline has a well-defined set of states a job moves through.

## Decision

Use `UUID` primary keys (generated via `gen_random_uuid()`) and a PostgreSQL `ENUM` type (`job_status`) for the pipeline state machine.

The `job_status` enum defines these states:
`scraped` → `scoring` → `scored` → `reviewing` → `approved` / `rejected` → `generating` → `applying` → `applied` → `error`

## Consequences

- **Globally unique IDs.** UUIDs prevent collisions if data is ever merged or exported. No coordination needed between services generating references.
- **Type-safe status.** The ENUM prevents invalid status values at the database level. A typo in application code causes a hard error, not silent data corruption.
- **Clear state machine.** The defined enum values document the pipeline stages. Adding a new state requires an explicit `ALTER TYPE` migration.
- **Schema rigidity.** Changing enum values requires a migration, unlike free-text columns. This is intentional — pipeline state changes should be deliberate.
- **UUID storage overhead.** 16 bytes vs 4 bytes for an integer. Negligible at the expected scale (thousands of rows, not billions).

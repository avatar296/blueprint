# ADR-010: Deferred Authentication with Authentik OIDC

## Status

Accepted

## Context

The Dashboard exposes a web UI for reviewing and approving job applications. In production, it needs authentication to prevent unauthorized access. Options include:

- Build authentication into the Dashboard from day one (NextAuth + Authentik OIDC)
- Defer authentication — develop without auth, add it when preparing for production deployment
- Use basic auth or API keys as a stopgap

Authentication adds complexity (OIDC provider setup, token handling, session management) that slows down initial development when the Dashboard is only accessed locally.

## Decision

Defer Authentik integration. The scaffolding includes:

- NextAuth environment variables pre-configured in `docker-compose.yml` and `.env.example`
- Authentik OIDC variables commented out, ready to uncomment
- Authentik Docker service definition commented out in `docker-compose.yml` with a link to setup docs

Development works without authentication. Enabling auth requires uncommenting the Authentik service, filling in OIDC credentials, and configuring the NextAuth provider.

## Consequences

- **Faster iteration.** No auth setup required to start developing and testing the Dashboard.
- **Clear upgrade path.** All the configuration scaffolding is in place. Enabling auth is a configuration change, not an architecture change.
- **Insecure by default.** The Dashboard is open during development. Must be addressed before any network-exposed deployment.
- **No premature complexity.** OIDC provider configuration, token refresh, and session management are deferred until actually needed.

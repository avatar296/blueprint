# ADR-006: Next.js Standalone Output with Multistage Docker Build

## Status

Accepted

## Context

The Dashboard is a Next.js application that needs to run in a Docker container. Options for containerization include:

- Copy the entire `node_modules` and `.next` build output — simple but produces 1GB+ images
- Use Next.js `output: "standalone"` with a multistage Docker build — minimal production image
- Static export (`output: "export"`) served by nginx — no SSR, limits future API route usage

The Dashboard will likely need server-side rendering and API routes for database queries.

## Decision

Configure Next.js with `output: "standalone"` in `next.config.ts` and use a 3-stage Docker build:

1. **deps** — Install `node_modules` via `npm ci`
2. **builder** — Copy modules, build the application
3. **runner** — Copy only the standalone output and static assets, run as non-root `nextjs` user

## Consequences

- **Minimal image size.** The final image contains only the files needed to run, not the full `node_modules` tree. Typically ~100MB vs 1GB+.
- **Security.** The production container runs as a non-root user (`nextjs:nodejs`, UID 1001) with no build tooling present.
- **SSR capability preserved.** Unlike static export, the standalone server supports server-side rendering and API routes.
- **Build complexity.** Three Dockerfile stages are more complex than a single stage, but the pattern is well-documented and standard for Next.js.
- **Pinned Node.js version.** All three stages use `node:20-alpine` for consistency.

# ADR-003: Playwright Stealth Mode for Browser Automation

## Status

Accepted

## Context

The Scout and Applier services need to interact with job boards (LinkedIn, Indeed, Workday, Lever). Options include:

- REST API scraping — fast and lightweight, but most job boards lack public APIs or aggressively rate-limit them
- Selenium/WebDriver — mature but heavyweight, detectable by anti-bot systems
- Playwright — modern browser automation with stealth plugins, cross-browser support, and strong async Python bindings

## Decision

Use Playwright with stealth mode for both Scout (scraping job boards) and Applier (filling application forms). Chromium is installed inside each container at build time via `playwright install chromium`.

## Consequences

- **Bypasses anti-bot detection.** Stealth mode mimics human browsing patterns, reducing blocks from LinkedIn and Indeed.
- **Shared automation library.** Both Scout and Applier use the same Playwright dependency, reducing the learning surface.
- **Heavy container images.** Chromium adds ~400MB to each container. Accepted tradeoff for reliability.
- **Fragile selectors.** Job board UI changes can break scrapers. This is inherent to any browser automation approach and requires ongoing maintenance.
- **System dependencies.** Playwright requires specific shared libraries (libnss3, libatk, etc.) installed in the container, handled via apt in the Dockerfiles.

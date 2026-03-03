# ADR-007: LaTeX for ATS-Optimized PDF Generation

## Status

Accepted

## Context

The Applier service generates tailored resumes and cover letters for each approved job. Options include:

- HTML-to-PDF (Puppeteer/Playwright) — flexible styling but inconsistent text extraction by ATS parsers
- LaTeX — precise typographic control, clean text layer for ATS parsing, industry-standard for technical resumes
- Word/DOCX generation — good ATS compatibility but limited layout control

ATS (Applicant Tracking Systems) parse uploaded PDFs to extract structured data. PDFs with clean text layers parse reliably; those generated from HTML rendering often produce garbled text extraction.

## Decision

Use TeX Live (installed in the Applier container via `texlive-latex-base`, `texlive-latex-recommended`, `texlive-latex-extra`) with Jinja2 templates to generate LaTeX source, then compile to PDF.

## Consequences

- **ATS-friendly output.** LaTeX-generated PDFs have a clean, extractable text layer that parses reliably in Workday, Lever, Greenhouse, and other ATS platforms.
- **Precise formatting.** Full control over typography, spacing, and layout without fighting CSS rendering differences.
- **Template-driven.** Jinja2 templates allow per-job customization (keywords, role emphasis) while maintaining consistent formatting.
- **Large container image.** TeX Live adds ~300MB to the Applier container. Accepted tradeoff for output quality.
- **LaTeX expertise required.** Template maintenance requires LaTeX knowledge, though Jinja2 abstracts most of the complexity.

# ADR-005: Python src-layout with pyproject.toml

## Status

Accepted

## Context

The three Python services (Scout, Evaluator, Applier) each need a packaging structure. Options include:

- Flat layout (`scout/main.py` at the repo root) — simple but prone to import ambiguity
- src-layout (`src/scout/main.py`) with `pyproject.toml` — modern Python best practice
- Poetry/PDM/Hatch — feature-rich but add tooling complexity for services that are containerized anyway

## Decision

Use the src-layout convention with `pyproject.toml` and setuptools as the build backend. Each service follows this structure:

```
services/<name>/
├── pyproject.toml
├── src/
│   └── <name>/
│       ├── __init__.py
│       └── main.py
└── Dockerfile
```

Services are installed in their containers via `pip install --no-cache-dir .` which reads `pyproject.toml`.

## Consequences

- **No import ambiguity.** The `src/` directory is not on `sys.path` during development unless explicitly installed, preventing accidental imports of the source tree instead of the installed package.
- **Standard tooling.** `pyproject.toml` is the PEP 621 standard. Works with pip, setuptools, and any PEP 517-compliant build frontend.
- **Dev install support.** `pip install -e .` enables editable installs for local development outside Docker.
- **Consistent structure.** All three Python services follow the same layout, making it easy to navigate between them.
- **Minimal boilerplate.** No lock files or extra tooling beyond pip and setuptools. Dependencies are pinned with minimum versions (`>=`) in `pyproject.toml`, with Docker builds providing reproducibility.

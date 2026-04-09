#!/usr/bin/env python3
"""Single-command entry point: python run_benchmark.py

Equivalent to: uv run python -m benchmark.cli run
"""

from benchmark.cli import cli

if __name__ == "__main__":
    cli(["run"])

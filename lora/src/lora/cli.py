"""CLI entry point for LoRA training data generation pipeline."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

log = logging.getLogger("lora")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable debug logging")
def cli(verbose: bool) -> None:
    """LoRA training data generation from KYB cascade signals."""
    _setup_logging(verbose)


@cli.command()
@click.option("--companies", "-c", required=True, type=click.Path(exists=True, path_type=Path),
              help="Company list (JSON or CSV)")
@click.option("--output", "-o", type=click.Path(path_type=Path), default=Path("lora/data/captured.jsonl"))
@click.option("--concurrency", type=int, default=3)
@click.option("--ollama-url", default="http://localhost:11434")
@click.option("--ollama-model", default="llama3:8b")
@click.option("--ollama-timeout", type=float, default=10.0)
@click.option("--vision-model", default=None, help="Ollama vision model (optional)")
def capture(
    companies: Path,
    output: Path,
    concurrency: int,
    ollama_url: str,
    ollama_model: str,
    ollama_timeout: float,
    vision_model: str | None,
) -> None:
    """Run cascade against company list, capture training signals."""
    from .capture import load_company_list, run_capture_batch

    company_list = load_company_list(companies)
    log.info("Starting capture: %d companies, concurrency=%d", len(company_list), concurrency)

    results = asyncio.run(run_capture_batch(
        company_list,
        concurrency=concurrency,
        ollama_base_url=ollama_url,
        ollama_model=ollama_model,
        ollama_timeout=ollama_timeout,
        ollama_vision_model=vision_model,
        output_path=output,
    ))

    click.echo(f"\nCapture complete: {len(results)} results saved to {output}")


@cli.command()
@click.option("--captured", "-i", required=True, type=click.Path(exists=True, path_type=Path),
              help="Captured results JSONL from capture step")
@click.option("--training-output", type=click.Path(path_type=Path),
              default=Path("lora/data/training.jsonl"))
@click.option("--edge-case-output", type=click.Path(path_type=Path),
              default=Path("lora/data/edge_cases.json"))
@click.option("--stats-output", type=click.Path(path_type=Path),
              default=Path("lora/data/generation_stats.json"))
@click.option("--none-oversample", type=float, default=2.0,
              help="Repeat factor for NONE training examples (default 2x)")
def prepare(
    captured: Path,
    training_output: Path,
    edge_case_output: Path,
    stats_output: Path,
    none_oversample: float,
) -> None:
    """Filter captured signals, generate training JSONL + edge case set."""
    from .capture import load_captured_results
    from .edge_cases import build_edge_case_golden_set
    from .filter import label_captured_results
    from .formatter import format_training_data, write_generation_stats

    results = load_captured_results(captured)
    high_conf, low_conf = label_captured_results(results)

    training_count = format_training_data(
        high_conf, training_output, none_oversample=none_oversample,
    )

    build_edge_case_golden_set(low_conf, edge_case_output, goal="careers")
    write_generation_stats(high_conf, low_conf, training_count, stats_output)

    click.echo("\nPrepare complete:")
    click.echo(f"  Training data: {training_count} examples → {training_output}")
    click.echo(f"  Edge cases: {len(low_conf)} cases → {edge_case_output}")
    click.echo(f"  Stats: {stats_output}")


@cli.command()
@click.option("--training-data", "-t", required=True,
              type=click.Path(exists=True, path_type=Path))
@click.option("--base-model", default="meta-llama/Meta-Llama-3-8B-Instruct")
@click.option("--output", type=click.Path(path_type=Path), default=Path("lora/adapters/kyb-v1"))
@click.option("--epochs", type=int, default=3)
@click.option("--batch-size", type=int, default=4)
@click.option("--learning-rate", type=float, default=2e-4)
def train(
    training_data: Path,
    base_model: str,
    output: Path,
    epochs: int,
    batch_size: int,
    learning_rate: float,
) -> None:
    """Train LoRA adapter (delegates to benchmark scaffold)."""
    try:
        from benchmark.lora.training import train_lora
        from benchmark.config import load_config
    except ImportError:
        click.echo("LoRA training deps not installed. Run: uv sync --extra lora", err=True)
        sys.exit(1)

    config = load_config()
    config.lora_epochs = epochs
    config.lora_batch_size = batch_size
    config.lora_learning_rate = learning_rate

    adapter_path = train_lora(
        base_model=base_model,
        train_data=str(training_data),
        output_dir=str(output),
        config=config,
    )
    click.echo(f"\nLoRA adapter saved to: {adapter_path}")


@cli.command()
@click.option("--adapter", required=True, type=click.Path(exists=True, path_type=Path))
@click.option("--base-model", default="meta-llama/Meta-Llama-3-8B-Instruct")
@click.option("--quant-levels", default="f16,q8_0,q4_0")
@click.option("--model-name", default="llama3-kyb-lora")
def merge(
    adapter: Path,
    base_model: str,
    quant_levels: str,
    model_name: str,
) -> None:
    """Merge LoRA adapter and export GGUF for Ollama."""
    try:
        from benchmark.lora.merge import merge_and_export_gguf
    except ImportError:
        click.echo("LoRA merge deps not installed. Run: uv sync --extra lora", err=True)
        sys.exit(1)

    levels = [level.strip() for level in quant_levels.split(",")]
    tags = merge_and_export_gguf(
        base_model=base_model,
        adapter_path=str(adapter),
        output_dir="lora/merged_models",
        quant_levels=levels,
        ollama_model_name=model_name,
    )
    click.echo(f"\nOllama model tags created: {', '.join(tags)}")


@cli.command()
@click.option("--edge-cases", type=click.Path(exists=True, path_type=Path), default=None,
              help="Edge case golden set to include in evaluation")
@click.option("--runs", type=int, default=20)
@click.option("--ollama-url", default="http://localhost:11434")
def evaluate(
    edge_cases: Path | None,
    runs: int,
    ollama_url: str,
) -> None:
    """Run benchmark with base + LoRA variants against golden + edge case sets."""
    from benchmark.config import load_config
    from benchmark.harness.runner import run_benchmark, save_results
    from benchmark.report.markdown import generate_report
    from benchmark.report.plots import generate_all_plots

    config = load_config()
    config.benchmark_runs = runs
    config.ollama_base_url = ollama_url
    config.output_dir = Path("lora/results")

    extra_dirs = [edge_cases.parent] if edge_cases else None

    report = asyncio.run(run_benchmark(config, extra_golden_dirs=extra_dirs))

    if not report.scores:
        click.echo("No results. Check Ollama and model availability.", err=True)
        sys.exit(1)

    save_results(config, report)
    generate_report(report.scores, report.metrics, report.pareto, config.output_dir)
    generate_all_plots(
        report.scores, report.metrics, report.pareto, report.raw_latencies, config.output_dir,
    )

    click.echo(f"\nEvaluation complete. Results in {config.output_dir}/")


@cli.command("generate-company-list")
@click.option("--output", type=click.Path(path_type=Path), default=Path("lora/company_list.json"))
@click.option("--limit", type=int, default=300)
@click.option("--none-ratio", type=float, default=0.35,
              help="Target ratio of companies likely without careers pages")
def generate_company_list(output: Path, limit: int, none_ratio: float) -> None:
    """Generate a company list from the database for training data capture."""
    import json as json_mod

    from common.db import get_pool

    pool = get_pool()

    # Companies WITH known careers signals (positive examples).
    with_careers_limit = int(limit * (1 - none_ratio))
    without_careers_limit = limit - with_careers_limit

    with pool.connection() as conn:
        # Companies that have careers signals (known positives).
        rows_positive = conn.execute("""
            SELECT c.id, c.name, c.website, c.city, c.state
            FROM companies c
            JOIN company_signals cs ON c.id = cs.company_id AND cs.check_type = 'careers'
            WHERE c.website IS NOT NULL
              AND cs.result->>'careers_url' IS NOT NULL
            ORDER BY random()
            LIMIT %s
        """, [with_careers_limit]).fetchall()

        # Companies WITHOUT careers signals (likely NONE cases).
        rows_negative = conn.execute("""
            SELECT c.id, c.name, c.website, c.city, c.state
            FROM companies c
            LEFT JOIN company_signals cs ON c.id = cs.company_id AND cs.check_type = 'careers'
            WHERE c.website IS NOT NULL
              AND (cs.id IS NULL OR cs.result->>'careers_url' IS NULL)
              AND c.employee_count IS NOT NULL
              AND c.employee_count < 50
            ORDER BY random()
            LIMIT %s
        """, [without_careers_limit]).fetchall()

    companies = []
    for row in rows_positive:
        companies.append({
            "id": str(row[0]),
            "name": row[1],
            "website": row[2],
            "city": row[3],
            "state": row[4],
            "expected_type": "positive",
        })
    for row in rows_negative:
        companies.append({
            "id": str(row[0]),
            "name": row[1],
            "website": row[2],
            "city": row[3],
            "state": row[4],
            "expected_type": "none",
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json_mod.dump(companies, f, indent=2)

    click.echo(
        f"Generated company list: {len(companies)} total "
        f"({len(rows_positive)} positive, {len(rows_negative)} expected-NONE) → {output}"
    )


def main() -> None:
    cli()


if __name__ == "__main__":
    main()

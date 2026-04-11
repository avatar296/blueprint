"""CLI entry point for the benchmark harness."""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click

from .config import load_config

log = logging.getLogger("benchmark")


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
    """KYB Quantization & LoRA Benchmark Harness."""
    _setup_logging(verbose)


@cli.command()
@click.option("--models", "-m", multiple=True, help="Specific Ollama model tags to benchmark")
@click.option("--runs", "-n", type=int, default=None, help="Runs per test case (default: 50)")
@click.option("--warmup", type=int, default=None, help="Warmup runs (default: 3)")
@click.option("--golden-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output-dir", type=click.Path(path_type=Path), default=None)
@click.option("--ollama-url", type=str, default=None, help="Ollama base URL")
@click.option("--skip-lora", is_flag=True, help="Skip LoRA model variants")
@click.option("--extra-golden-dir", multiple=True, type=click.Path(exists=True, path_type=Path),
              help="Additional golden test set directories (e.g. edge cases)")
def run(
    models: tuple[str, ...],
    runs: int | None,
    warmup: int | None,
    golden_dir: Path | None,
    output_dir: Path | None,
    ollama_url: str | None,
    skip_lora: bool,
    extra_golden_dir: tuple[Path, ...],
) -> None:
    """Run the quantization benchmark against golden test sets."""
    config = load_config()

    if runs is not None:
        config.benchmark_runs = runs
    if warmup is not None:
        config.warmup_runs = warmup
    if golden_dir is not None:
        config.golden_data_dir = golden_dir
    if output_dir is not None:
        config.output_dir = output_dir
    if ollama_url is not None:
        config.ollama_base_url = ollama_url
    if skip_lora:
        config.lora_models = []

    model_list = list(models) if models else None

    log.info("Benchmark config: %d runs/case, %d warmup, output=%s",
             config.benchmark_runs, config.warmup_runs, config.output_dir)

    from .harness.runner import run_benchmark, save_results
    from .report.markdown import generate_report
    from .report.plots import generate_all_plots

    extra_dirs = list(extra_golden_dir) if extra_golden_dir else None
    report = asyncio.run(run_benchmark(config, models=model_list, extra_golden_dirs=extra_dirs))

    if not report.scores:
        log.error("No benchmark results — check Ollama availability and model tags")
        sys.exit(1)

    # Save results.
    save_results(config, report)

    # Generate reports.
    generate_report(report.scores, report.metrics, report.pareto, config.output_dir)
    generate_all_plots(
        report.scores, report.metrics, report.pareto, report.raw_latencies, config.output_dir,
    )

    # Print summary.
    click.echo("\n" + "=" * 70)
    click.echo("BENCHMARK COMPLETE")
    click.echo("=" * 70)

    pareto_opts = [p for p in report.pareto if p.is_pareto_optimal]
    if pareto_opts:
        click.echo("\nPareto-optimal configurations:")
        for p in pareto_opts:
            click.echo(
                f"  {p.model_id}: accuracy={p.accuracy:.1%} "
                f"p50={p.latency_p50_ms:.1f}ms "
                f"mem={p.memory_mb:.0f}MB "
                f"cost=${p.cost_per_1k:.4f}/1k"
            )

    click.echo(f"\nResults saved to: {config.output_dir}/")
    click.echo("  comparison_report.json")
    click.echo("  comparison_report.md")
    click.echo("  accuracy_vs_cost.png")
    click.echo("  latency_distributions.png")


@cli.command()
@click.option("--base-model", required=True, help="HuggingFace base model ID")
@click.option("--train-data", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--output", type=click.Path(path_type=Path), default=Path("benchmark/lora_adapters"))
@click.option("--epochs", type=int, default=None)
@click.option("--batch-size", type=int, default=None)
@click.option("--learning-rate", type=float, default=None)
def train(
    base_model: str,
    train_data: Path,
    output: Path,
    epochs: int | None,
    batch_size: int | None,
    learning_rate: float | None,
) -> None:
    """Train a LoRA adapter for KYB element classification."""
    config = load_config()

    if epochs is not None:
        config.lora_epochs = epochs
    if batch_size is not None:
        config.lora_batch_size = batch_size
    if learning_rate is not None:
        config.lora_learning_rate = learning_rate

    try:
        from .lora.training import train_lora
    except ImportError:
        click.echo("LoRA dependencies not installed. Run: uv sync --extra lora", err=True)
        sys.exit(1)

    adapter_path = train_lora(
        base_model=base_model,
        train_data=str(train_data),
        output_dir=str(output),
        config=config,
    )
    click.echo(f"LoRA adapter saved to: {adapter_path}")


@cli.command()
@click.option("--adapter", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--base-model", required=True, help="HuggingFace base model ID")
@click.option("--quant-levels", default="f16,q8_0,q4_0", help="Comma-separated GGUF quant levels")
@click.option("--model-name", default="llama3-kyb-lora", help="Ollama model name prefix")
def merge(
    adapter: Path,
    base_model: str,
    quant_levels: str,
    model_name: str,
) -> None:
    """Merge LoRA adapter into base model and export as GGUF for Ollama."""
    try:
        from .lora.merge import merge_and_export_gguf
    except ImportError:
        click.echo("LoRA dependencies not installed. Run: uv sync --extra lora", err=True)
        sys.exit(1)

    levels = [level.strip() for level in quant_levels.split(",")]
    tags = merge_and_export_gguf(
        base_model=base_model,
        adapter_path=str(adapter),
        output_dir="benchmark/merged_models",
        quant_levels=levels,
        ollama_model_name=model_name,
    )
    click.echo(f"Created Ollama model tags: {', '.join(tags)}")


@cli.command()
@click.option("--golden-dir", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--output", type=click.Path(path_type=Path), default=None)
def generate_training_data(golden_dir: Path | None, output: Path | None) -> None:
    """Generate JSONL training data from golden test sets."""
    config = load_config()
    if golden_dir:
        config.golden_data_dir = golden_dir

    from .lora.data import generate_training_template

    out_path = output or Path("benchmark/golden_data/training.jsonl")
    generate_training_template(config.golden_data_dir, out_path)
    click.echo(f"Training data written to: {out_path}")


@cli.command("report")
@click.option("--results-dir", type=click.Path(exists=True, path_type=Path), default=None)
def regenerate_report(results_dir: Path | None) -> None:
    """Regenerate reports from existing benchmark results."""
    import json as json_mod

    config = load_config()
    if results_dir:
        config.output_dir = results_dir

    json_path = config.output_dir / "comparison_report.json"
    if not json_path.exists():
        click.echo(f"No results found at {json_path}. Run the benchmark first.", err=True)
        sys.exit(1)

    from .golden.schema import ParetoPoint, VariantMetrics, VariantScore
    from .report.markdown import generate_report
    from .report.plots import generate_all_plots

    with open(json_path) as f:
        data = json_mod.load(f)

    scores = [VariantScore.model_validate(s) for s in data["scores"]]
    metrics = [VariantMetrics.model_validate(m) for m in data["metrics"]]
    pareto = [ParetoPoint.model_validate(p) for p in data["pareto"]]

    generate_report(scores, metrics, pareto, config.output_dir)

    # For plots we need raw latencies — reconstruct from raw files.
    raw_latencies: dict[str, list[float]] = {}
    for score in scores:
        safe_name = score.model_id.replace(":", "_").replace("/", "_")
        raw_path = config.output_dir / f"raw_{safe_name}.json"
        if raw_path.exists():
            with open(raw_path) as f:
                raw_data = json_mod.load(f)
            raw_latencies[score.model_id] = [r["latency_ms"] for r in raw_data]

    generate_all_plots(scores, metrics, pareto, raw_latencies, config.output_dir)
    click.echo(f"Reports regenerated in {config.output_dir}/")


def main() -> None:
    """Entry point for ``python -m benchmark.cli``."""
    cli()


if __name__ == "__main__":
    main()

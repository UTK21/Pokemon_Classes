from __future__ import annotations

import json

import click

from ast_pruner.benchmark import benchmark_file, format_report
from ast_pruner.models import OutputFormat
from ast_pruner.pruner import run
from ast_pruner.report import generate_report


@click.group()
def main() -> None:
    """ast-pruner: semantically prune source files to reduce LLM context token count."""


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option(
    "--symbols", "-s", default="",
    help="Comma-separated symbol names to extract. Defaults to all exports.",
)
@click.option(
    "--depth", "-d", default=3, show_default=True,
    help="Maximum import recursion depth.",
)
@click.option(
    "--output", "-o", default=None,
    help="Write output to this file instead of stdout.",
)
@click.option(
    "--format", "-f", "fmt",
    type=click.Choice(["text", "json"]), default="text", show_default=True,
    help="Output format.",
)
def prune(file: str, symbols: str, depth: int, output: str | None, fmt: str) -> None:
    """Prune FILE to the requested SYMBOLS and their dependency signatures."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()]
    result_text = run(file, symbol_list, depth, OutputFormat(fmt))

    if output:
        with open(output, "w", encoding="utf-8") as f:
            f.write(result_text)
        click.echo(f"Written to {output}")
    else:
        click.echo(result_text, nl=False)


@main.command()
@click.argument("file", type=click.Path(exists=True))
@click.option("--symbols", "-s", default="",
              help="Comma-separated symbol names. Defaults to all exports.")
@click.option("--depth", "-d", default=3, show_default=True,
              help="Maximum import recursion depth.")
@click.option("--format", "-f", "fmt",
              type=click.Choice(["text", "json"]), default="text", show_default=True,
              help="Output format.")
def benchmark(file: str, symbols: str, depth: int, fmt: str) -> None:
    """Measure token reduction vs. pasting full files as baseline."""
    symbol_list = [s.strip() for s in symbols.split(",") if s.strip()] or None
    result = benchmark_file(file, symbol_list, depth)

    if fmt == "json":
        click.echo(json.dumps(result.to_dict(), indent=2))
    else:
        click.echo(format_report(result))


@main.command()
@click.option("--log", "log_path", required=True, type=click.Path(),
              help="Path to the usage JSONL log file.")
@click.option("--output", "-o", required=True, type=click.Path(),
              help="Path to write the HTML dashboard.")
def report(log_path: str, output: str) -> None:
    """Generate an HTML dashboard visualising token savings from a usage log."""
    agg = generate_report(log_path, output)
    click.echo(f"Wrote dashboard to {output}")
    click.echo(f"  invocations: {agg['total_invocations']}")
    click.echo(f"  tokens saved: {agg['total_tokens_saved']:,}")
    click.echo(f"  avg reduction: {agg['avg_reduction_pct']}%")

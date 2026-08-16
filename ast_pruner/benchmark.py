"""
Evaluation metrics for ast-pruner.

Measures the token reduction achieved by pruning, compared to the
"naive baseline" of pasting the entry file plus every transitively
imported local file in full.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Optional

from ast_pruner.graph import build_graph
from ast_pruner.models import OutputFormat
from ast_pruner.pruner import _get_all_exports, run
from ast_pruner.renderer import estimate_tokens


@dataclass
class FileMetric:
    rel_path: str
    raw_bytes: int
    raw_tokens: int
    pruned_tokens: int
    reduction_pct: float


@dataclass
class BenchmarkResult:
    entry_file: str
    requested_symbols: list[str]
    depth: int

    # Naive baseline: entry file + all transitively imported files, full source
    baseline_files: int
    baseline_tokens: int

    # Pruned output
    pruned_files: int
    pruned_tokens: int

    # Derived metrics
    tokens_saved: int
    reduction_pct: float
    compression_ratio: float  # baseline / pruned

    per_file: list[FileMetric] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "entry_file": self.entry_file,
            "requested_symbols": self.requested_symbols,
            "depth": self.depth,
            "baseline": {
                "files": self.baseline_files,
                "tokens": self.baseline_tokens,
            },
            "pruned": {
                "files": self.pruned_files,
                "tokens": self.pruned_tokens,
            },
            "tokens_saved": self.tokens_saved,
            "reduction_pct": round(self.reduction_pct, 2),
            "compression_ratio": round(self.compression_ratio, 2),
            "per_file": [
                {
                    "path": fm.rel_path,
                    "raw_tokens": fm.raw_tokens,
                    "pruned_tokens": fm.pruned_tokens,
                    "reduction_pct": round(fm.reduction_pct, 2),
                }
                for fm in self.per_file
            ],
        }


def _read_tokens(abs_path: str) -> tuple[int, int]:
    """Return (raw_bytes, raw_tokens) for a file."""
    with open(abs_path, "rb") as f:
        data = f.read()
    text = data.decode("utf-8", errors="replace")
    return len(data), estimate_tokens(text)


def benchmark_file(
    entry_path: str,
    symbols: Optional[list[str]] = None,
    depth: int = 3,
) -> BenchmarkResult:
    """
    Run a full benchmark for a single entry file.

    Compares:
      - Baseline: full source of entry + all transitive local imports
      - Pruned:   ast-pruner output for the same depth/symbols
    """
    abs_path = os.path.abspath(entry_path)
    initial = set(symbols) if symbols else _get_all_exports(abs_path)

    # Build graph to enumerate all files that would be visible in baseline too
    graph = build_graph(abs_path, initial, max_depth=depth)

    # Baseline: raw token count of every file reachable in the graph
    baseline_tokens = 0
    per_file_raw: dict[str, int] = {}
    for node_path in graph.nodes.keys():
        _, raw_tokens = _read_tokens(node_path)
        per_file_raw[node_path] = raw_tokens
        baseline_tokens += raw_tokens

    # Pruned: run the actual pruner and parse its JSON output
    pruned_json = run(abs_path, symbols or [], depth, OutputFormat.JSON)
    pruned_data = json.loads(pruned_json)
    pruned_tokens = pruned_data["total_tokens"]

    # Per-file metrics
    per_file: list[FileMetric] = []
    pruned_by_path = {f["path"]: f for f in pruned_data["files"]}

    for node_path, raw_tokens in per_file_raw.items():
        pruned_tok = pruned_by_path.get(node_path, {}).get("estimated_tokens", 0)
        reduction = ((raw_tokens - pruned_tok) / raw_tokens * 100) if raw_tokens else 0.0
        per_file.append(FileMetric(
            rel_path=os.path.relpath(node_path),
            raw_bytes=0,
            raw_tokens=raw_tokens,
            pruned_tokens=pruned_tok,
            reduction_pct=reduction,
        ))

    tokens_saved = baseline_tokens - pruned_tokens
    reduction_pct = (tokens_saved / baseline_tokens * 100) if baseline_tokens else 0.0
    compression_ratio = (baseline_tokens / pruned_tokens) if pruned_tokens else float("inf")

    return BenchmarkResult(
        entry_file=os.path.relpath(abs_path),
        requested_symbols=list(initial),
        depth=depth,
        baseline_files=len(graph.nodes),
        baseline_tokens=baseline_tokens,
        pruned_files=len(pruned_data["files"]),
        pruned_tokens=pruned_tokens,
        tokens_saved=tokens_saved,
        reduction_pct=reduction_pct,
        compression_ratio=compression_ratio,
        per_file=per_file,
    )


def format_report(result: BenchmarkResult) -> str:
    """Pretty-print a benchmark result as a text report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append(f"  ast-pruner benchmark — {result.entry_file}")
    lines.append("=" * 70)
    lines.append(f"Requested symbols : {', '.join(result.requested_symbols) or '<all exports>'}")
    lines.append(f"Max depth         : {result.depth}")
    lines.append("")
    lines.append(f"{'Metric':<25} {'Baseline':>15} {'Pruned':>15} {'Saved':>12}")
    lines.append("-" * 70)
    lines.append(f"{'Files':<25} {result.baseline_files:>15} {result.pruned_files:>15} {'-':>12}")
    lines.append(f"{'Tokens':<25} {result.baseline_tokens:>15} {result.pruned_tokens:>15} "
                 f"{result.tokens_saved:>12}")
    lines.append("")
    lines.append(f"Reduction         : {result.reduction_pct:.1f}%")
    lines.append(f"Compression ratio : {result.compression_ratio:.2f}x")
    lines.append("")
    lines.append("Per-file breakdown:")
    lines.append(f"  {'File':<45} {'Raw':>8} {'Pruned':>8} {'Cut':>6}")
    lines.append("  " + "-" * 70)
    for fm in result.per_file:
        path = fm.rel_path if len(fm.rel_path) <= 45 else "..." + fm.rel_path[-42:]
        lines.append(f"  {path:<45} {fm.raw_tokens:>8} {fm.pruned_tokens:>8} "
                     f"{fm.reduction_pct:>5.0f}%")
    lines.append("")
    return "\n".join(lines)

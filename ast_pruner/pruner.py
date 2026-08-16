from __future__ import annotations

import os

from ast_pruner.extractor import extract_full, extract_signatures
from ast_pruner.graph import build_graph
from ast_pruner.models import DependencyNode, OutputFormat, PrunedFile, PruneResult
from ast_pruner.parsers import get_parser
from ast_pruner.renderer import build_pruned_file, estimate_tokens, render


def _get_all_exports(abs_path: str) -> set[str]:
    """Return all exported symbol names from a file."""
    try:
        pf = get_parser(abs_path).parse(abs_path)
        exported = {s.name for s in pf.symbols if s.is_exported}
        if not exported:
            # Python: all top-level symbols are "exported"
            exported = {s.name for s in pf.symbols}
        return exported
    except Exception:
        return set()


def run(
    file: str,
    symbols: list[str],
    depth: int,
    fmt: OutputFormat,
) -> str:
    abs_path = os.path.abspath(file)

    # If no symbols specified, use all exports
    initial_symbols: set[str] = set(symbols) if symbols else _get_all_exports(abs_path)

    # Build dependency graph via BFS
    graph = build_graph(abs_path, initial_symbols, max_depth=depth)

    # Extract and assemble pruned files in BFS order (entry first, then by depth)
    ordered_nodes = sorted(graph.nodes.values(), key=lambda n: n.depth)

    pruned_files: list[PrunedFile] = []
    for node in ordered_nodes:
        if node.parsed_file is None:
            continue

        is_entry = node.depth == 0
        pf = node.parsed_file

        if is_entry:
            source = extract_full(pf, node.requested_symbols)
        else:
            source = extract_signatures(pf, node.requested_symbols)

        kept = [s.name for s in pf.symbols if s.name in node.requested_symbols]
        pruned = build_pruned_file(
            abs_path=node.abs_path,
            depth=node.depth,
            is_entry=is_entry,
            kept_symbols=kept,
            pruned_source=source,
        )
        pruned_files.append(pruned)

    total_tokens = sum(pf.estimated_tokens for pf in pruned_files)

    result = PruneResult(
        entry_file=os.path.relpath(abs_path),
        requested_symbols=list(initial_symbols),
        files=pruned_files,
        total_tokens=total_tokens,
    )

    return render(result, fmt)

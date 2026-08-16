from __future__ import annotations

import re
from collections import deque
from typing import Callable

from ast_pruner.models import DependencyGraph, DependencyNode, ImportedSymbol, ParsedFile
from ast_pruner.parsers import get_parser
from ast_pruner.resolver import detect_language, resolve, resolve_python_import


def _identifiers_in_range(source: bytes, start: int, end: int) -> set[str]:
    chunk = source[start:end].decode("utf-8", errors="replace")
    return set(re.findall(r"\b([A-Za-z_$][A-Za-z0-9_$]*)\b", chunk))


def _resolve_specifier(specifier: str, importing_abs: str) -> str | None:
    """Resolve an import specifier to an absolute path, handling Python relative imports."""
    lang = detect_language(importing_abs)
    if lang == "python" and specifier.startswith("."):
        # Convert dot-prefix notation back to (dots, module_parts)
        dots = 0
        for ch in specifier:
            if ch == ".":
                dots += 1
            else:
                break
        remainder = specifier[dots:]
        parts = remainder.split(".") if remainder else []
        return resolve_python_import(parts, importing_abs, dots)
    return resolve(specifier, importing_abs)


def _needed_imports(
    pf: ParsedFile, requested_symbols: set[str]
) -> list[tuple[ImportedSymbol, set[str]]]:
    """
    For each import in pf, determine which exported names from that import
    are referenced by the requested symbols' source regions.
    Returns list of (ImportedSymbol, {names_needed_from_that_file}).
    """
    # Collect all identifiers used in the requested symbols
    used_ids: set[str] = set()
    for sym in pf.symbols:
        if sym.name in requested_symbols:
            used_ids |= _identifiers_in_range(pf.source, sym.start_byte, sym.end_byte)

    # Group imports by source_specifier
    by_spec: dict[str, list[ImportedSymbol]] = {}
    for imp in pf.imports:
        by_spec.setdefault(imp.source_specifier, []).append(imp)

    result: list[tuple[ImportedSymbol, set[str]]] = []
    for spec, imps in by_spec.items():
        needed: set[str] = set()
        rep_imp: ImportedSymbol | None = None
        for imp in imps:
            if imp.name in used_ids or imp.name == "*":
                needed.add(imp.alias)  # original export name in the source file
                rep_imp = imp
        if needed and rep_imp:
            result.append((rep_imp, needed))
    return result


def build_graph(
    entry_path: str,
    initial_symbols: set[str],
    max_depth: int,
) -> DependencyGraph:
    """
    BFS from entry_path, following imports up to max_depth levels.
    Returns a DependencyGraph with all reachable local files and the
    symbols needed from each.
    """
    graph = DependencyGraph()
    visited: set[str] = set()
    queue: deque[DependencyNode] = deque()

    # Parse and enqueue entry
    entry_pf = get_parser(entry_path).parse(entry_path)
    entry_node = DependencyNode(
        abs_path=entry_path,
        depth=0,
        requested_symbols=initial_symbols,
        parsed_file=entry_pf,
    )
    graph.nodes[entry_path] = entry_node
    graph.edges[entry_path] = []
    visited.add(entry_path)
    queue.append(entry_node)

    while queue:
        current = queue.popleft()
        if current.depth >= max_depth or current.parsed_file is None:
            continue

        for imp, needed_names in _needed_imports(current.parsed_file, current.requested_symbols):
            dep_abs = _resolve_specifier(imp.source_specifier, current.abs_path)
            if dep_abs is None:
                continue  # external package

            # Record edge regardless
            graph.edges[current.abs_path].append(dep_abs)

            if dep_abs in visited:
                # Merge needed symbols into existing node (handles diamond deps)
                if dep_abs in graph.nodes:
                    graph.nodes[dep_abs].requested_symbols |= needed_names
                continue

            try:
                dep_pf = get_parser(dep_abs).parse(dep_abs)
            except Exception:
                # Unreadable or unsupported file — skip
                visited.add(dep_abs)
                continue

            dep_node = DependencyNode(
                abs_path=dep_abs,
                depth=current.depth + 1,
                requested_symbols=needed_names,
                parsed_file=dep_pf,
            )
            graph.nodes[dep_abs] = dep_node
            graph.edges.setdefault(dep_abs, [])
            visited.add(dep_abs)
            queue.append(dep_node)

    return graph

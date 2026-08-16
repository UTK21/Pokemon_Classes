from __future__ import annotations

import json
import os

from ast_pruner.models import OutputFormat, PrunedFile, PruneResult


def estimate_tokens(source: str) -> int:
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(source))
    except ImportError:
        return max(1, len(source) // 4)


def render(result: PruneResult, fmt: OutputFormat) -> str:
    if fmt == OutputFormat.JSON:
        return _render_json(result)
    return _render_text(result)


def _render_text(result: PruneResult) -> str:
    parts: list[str] = []
    for pf in result.files:
        label = pf.rel_path
        parts.append(f"# === {label} ({pf.estimated_tokens} tokens) ===")
        parts.append(pf.pruned_source.strip())
        parts.append("")

    parts.append("# ---")
    parts.append(f"# Total: {result.total_tokens} tokens across {len(result.files)} file(s)")
    return "\n".join(parts) + "\n"


def _render_json(result: PruneResult) -> str:
    data = {
        "entry": result.entry_file,
        "requested_symbols": result.requested_symbols,
        "total_tokens": result.total_tokens,
        "files": [
            {
                "path": pf.abs_path,
                "rel_path": pf.rel_path,
                "depth": pf.depth,
                "is_entry": pf.is_entry,
                "symbols": pf.kept_symbols,
                "source": pf.pruned_source,
                "estimated_tokens": pf.estimated_tokens,
            }
            for pf in result.files
        ],
    }
    return json.dumps(data, indent=2)


def build_pruned_file(
    abs_path: str,
    depth: int,
    is_entry: bool,
    kept_symbols: list[str],
    pruned_source: str,
) -> PrunedFile:
    rel = os.path.relpath(abs_path)
    tokens = estimate_tokens(pruned_source)
    return PrunedFile(
        abs_path=abs_path,
        rel_path=rel,
        depth=depth,
        is_entry=is_entry,
        kept_symbols=kept_symbols,
        pruned_source=pruned_source,
        estimated_tokens=tokens,
    )

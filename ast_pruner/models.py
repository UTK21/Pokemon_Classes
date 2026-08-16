from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class OutputFormat(str, Enum):
    TEXT = "text"
    JSON = "json"


@dataclass
class ImportedSymbol:
    name: str           # local name used in this file
    alias: str          # original export name (same as name if no alias)
    source_specifier: str  # raw import path, e.g. "./utils" or "react"
    is_reexport: bool = False  # True for "export { x } from './y'"


@dataclass
class ParsedSymbol:
    name: str
    kind: str           # "function" | "class" | "variable" | "type" | "interface"
    start_byte: int
    end_byte: int
    start_line: int
    end_line: int
    is_exported: bool
    body_start_byte: Optional[int] = None  # None for types/interfaces
    body_end_byte: Optional[int] = None


@dataclass
class ParsedFile:
    abs_path: str
    language: str       # "python" | "javascript" | "typescript"
    source: bytes       # raw UTF-8 bytes for byte-accurate slicing
    symbols: list[ParsedSymbol] = field(default_factory=list)
    imports: list[ImportedSymbol] = field(default_factory=list)


@dataclass
class DependencyNode:
    abs_path: str
    depth: int          # 0 = entry file
    requested_symbols: set[str]
    parsed_file: Optional[ParsedFile] = None
    is_external: bool = False


@dataclass
class DependencyGraph:
    nodes: dict[str, DependencyNode] = field(default_factory=dict)
    edges: dict[str, list[str]] = field(default_factory=dict)  # abs_path -> [abs_path]


@dataclass
class PrunedFile:
    abs_path: str
    rel_path: str       # relative to cwd for display
    depth: int
    is_entry: bool
    kept_symbols: list[str]
    pruned_source: str
    estimated_tokens: int


@dataclass
class PruneResult:
    entry_file: str
    requested_symbols: list[str]
    files: list[PrunedFile]
    total_tokens: int
